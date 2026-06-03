"""
Verification and learning record store for SignalPilot.

Persists Analysis objects as JSON keyed by revision.
On next deploy, compares new Analysis against baseline to validate fixes.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from signalpilot.models import Analysis
from signalpilot.config import get_settings


class VerificationStore:
    """Persist and compare analyses for fix verification."""

    def __init__(self, data_dir: Optional[Path] = None) -> None:
        settings = get_settings()
        self._dir = (data_dir or Path(settings.data_dir)) / "verifications"
        self._dir.mkdir(parents=True, exist_ok=True)

    def save(self, analysis: Analysis) -> Path:
        """Persist analysis to disk. Returns the file path."""
        path = self._dir / f"{analysis.id}.json"
        path.write_text(analysis.model_dump_json(indent=2), encoding="utf-8")
        return path

    def load(self, analysis_id: str) -> Optional[Analysis]:
        """Load a previously saved analysis. Returns None if not found."""
        path = self._dir / f"{analysis_id}.json"
        if not path.exists():
            return None
        try:
            return Analysis.model_validate_json(path.read_text())
        except Exception:
            return None

    def list_analyses(self) -> list[str]:
        """Return all saved analysis IDs, sorted by modification time (newest first)."""
        return sorted(
            [p.stem for p in self._dir.glob("*.json")],
            key=lambda stem: (self._dir / f"{stem}.json").stat().st_mtime,
            reverse=True,
        )

    def compare(self, baseline: Analysis, current: Analysis) -> str:
        """
        Compare current analysis against baseline.

        Returns a human-readable string describing:
        - Fixed: findings in baseline that are NOT in current
        - Regressed: findings in current that are NOT in baseline
        - Unchanged: findings in both
        """
        baseline_rules = {(f.rule_id, f.target.name): f for f in baseline.findings}
        current_rules = {(f.rule_id, f.target.name): f for f in current.findings}

        fixed = [f for key, f in baseline_rules.items() if key not in current_rules]
        regressed = [f for key, f in current_rules.items() if key not in baseline_rules]
        unchanged = [f for key, f in baseline_rules.items() if key in current_rules]

        lines = [f"Verification: baseline {baseline.id} → current {current.id}"]

        if fixed:
            lines.append(f"\n✅ Fixed ({len(fixed)}):")
            for f in fixed:
                lines.append(f"  - [{f.severity.value}] {f.title}")

        if regressed:
            lines.append(f"\n🔴 New/Regressed ({len(regressed)}):")
            for f in regressed:
                lines.append(f"  + [{f.severity.value}] {f.title}")

        if unchanged:
            lines.append(f"\n⚠️  Unchanged ({len(unchanged)}):")
            for f in unchanged:
                lines.append(f"  ~ [{f.severity.value}] {f.title}")

        if not fixed and not regressed and not unchanged:
            lines.append("\n✅ No changes between baseline and current.")

        return "\n".join(lines)

    def save_by_revision(self, analysis: Analysis, revision: str) -> Path:
        """Save analysis under a revision key for easy lookup."""
        path = self._dir / f"rev_{revision}.json"
        path.write_text(analysis.model_dump_json(indent=2), encoding="utf-8")
        return path

    def load_by_revision(self, revision: str) -> Optional[Analysis]:
        """Load analysis for a specific revision."""
        path = self._dir / f"rev_{revision}.json"
        if not path.exists():
            return None
        try:
            return Analysis.model_validate_json(path.read_text())
        except Exception:
            return None
