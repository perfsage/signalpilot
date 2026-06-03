"""
Deep log analysis for PerfSage SignalPilot.

Provides:
- Log template/fingerprint clustering via drain3
- New-error-after-deploy detection
- Error-rate and log-volume regression detection
- Stacktrace/exception extraction
- Well-known pattern categorization
"""
from __future__ import annotations

import re
from collections import defaultdict
from typing import Optional

from drain3 import TemplateMiner
from drain3.template_miner_config import TemplateMinerConfig

from signalpilot.models import LogCluster


# ── Patterns ──────────────────────────────────────────────────────────────
ERROR_PATTERN = re.compile(
    r"(?i)\b(error|exception|fatal|critical|panic|traceback|fail(ed)?)\b"
)

STACKTRACE_PATTERN = re.compile(
    r"(?:at\s+[\w.$]+\([\w.]+:\d+\)"     # Java/Kotlin
    r"|File\s+\"[^\"]+\",\s+line\s+\d+"  # Python
    r"|goroutine\s+\d+\s+\["             # Go
    r"|#\d+\s+0x[0-9a-f]+"              # C/C++ panic
    r")"
)

# Pattern → category
CATEGORY_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"(?i)out.of.memory|oom|killed"), "oom"),
    (re.compile(r"(?i)gc pause|garbage collect"), "gc"),
    (re.compile(r"(?i)connection refused|econnrefused|connection reset"), "conn"),
    (re.compile(r"(?i)timeout|timed out|deadline exceeded"), "timeout"),
    (re.compile(r"(?i)dns|no such host|lookup fail"), "dns"),
    (re.compile(r"(?i)tls|ssl|certificate|x509"), "tls"),
    (re.compile(r"(?i)pool|max.connections|too many connections"), "pool"),
]

AUTH_RE = re.compile(r"(?i)(authorization:\s*\S+\s+)\S+")
KV_RE = re.compile(r"(?i)((?:password|token|secret|api_key|apikey)(?:[=:\s]+))\S{6,}")


def cluster_logs(
    before_logs: str,
    after_logs: str,
    max_clusters: int = 200,
) -> list[LogCluster]:
    """
    Cluster log lines using drain3. Compare before/after deploy windows.

    Returns LogCluster objects sorted by:
    1. is_new=True first
    2. Then by (count_after - count_before) descending (growth)
    """
    # Use a single miner so cluster IDs are consistent across both windows.
    # Process before lines first, then after lines.
    miner = _make_drain()

    before_lines = [l for l in before_logs.splitlines() if l.strip()]
    after_lines = [l for l in after_logs.splitlines() if l.strip()]

    before_counts: dict[str, int] = defaultdict(int)
    for line in before_lines:
        result = miner.add_log_message(line)
        if result:
            cluster_id = str(result["cluster_id"])
            before_counts[cluster_id] += 1

    after_counts: dict[str, int] = defaultdict(int)
    after_samples: dict[str, list[str]] = defaultdict(list)
    for line in after_lines:
        result = miner.add_log_message(line)
        if result:
            cluster_id = str(result["cluster_id"])
            after_counts[cluster_id] += 1
            if len(after_samples[cluster_id]) < 5:
                after_samples[cluster_id].append(line)

    # Build a mapping: cluster_id → template
    templates: dict[str, str] = {}
    for cluster in miner.drain.id_to_cluster.values():
        cid = str(cluster.cluster_id)
        templates[cid] = " ".join(cluster.log_template_tokens)

    all_cluster_ids = set(before_counts.keys()) | set(after_counts.keys())

    clusters: list[LogCluster] = []
    for cid in all_cluster_ids:
        cb = before_counts.get(cid, 0)
        ca = after_counts.get(cid, 0)
        template = templates.get(cid, cid)
        is_new = cb == 0 and ca > 0 and bool(ERROR_PATTERN.search(template))
        clusters.append(
            LogCluster(
                fingerprint=cid,
                template=template,
                count_before=cb,
                count_after=ca,
                is_new=is_new,
                sample_lines=after_samples.get(cid, [])[:5],
                category=_categorize(template),
            )
        )

    clusters.sort(key=lambda c: (not c.is_new, -(c.count_after - c.count_before)))
    return clusters[:max_clusters]


def _make_drain() -> TemplateMiner:
    """Create a configured drain3 TemplateMiner."""
    cfg = TemplateMinerConfig()
    cfg.parametrize_numeric_tokens = True
    return TemplateMiner(config=cfg)


def _categorize(template: str) -> Optional[str]:
    """Return a category string if the template matches a well-known pattern."""
    for pattern, category in CATEGORY_PATTERNS:
        if pattern.search(template):
            return category
    return None


def extract_stacktraces(log_text: str) -> list[str]:
    """
    Extract stacktrace blocks from log text.

    A stacktrace block starts at a STACKTRACE_PATTERN match and extends
    until a blank line or non-indented line.

    Returns up to 10 stacktrace blocks (truncated at 15 lines each).
    """
    lines = log_text.splitlines()
    blocks: list[str] = []
    i = 0

    while i < len(lines) and len(blocks) < 10:
        line = lines[i]
        if STACKTRACE_PATTERN.search(line):
            block: list[str] = [line]
            i += 1
            while i < len(lines) and len(block) < 15:
                next_line = lines[i]
                if not next_line.strip():
                    break
                if next_line and next_line[0] not in (" ", "\t") and not STACKTRACE_PATTERN.search(next_line):
                    break
                block.append(next_line)
                i += 1
            blocks.append("\n".join(block))
        else:
            i += 1

    return blocks


def error_rate(log_text: str) -> float:
    """
    Return fraction of lines matching ERROR_PATTERN.
    Returns 0.0 for empty input.
    """
    lines = [l for l in log_text.splitlines() if l.strip()]
    if not lines:
        return 0.0
    error_lines = sum(1 for l in lines if ERROR_PATTERN.search(l))
    return error_lines / len(lines)


def redact_log(text: str) -> str:
    """Redact secrets from log text."""
    text = AUTH_RE.sub(r"\1[REDACTED]", text)
    text = KV_RE.sub(r"\1[REDACTED]", text)
    return text


# Keep old name for any existing callers
categorise_cluster = _categorize
