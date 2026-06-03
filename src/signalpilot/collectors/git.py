"""
Git correlation collector for PerfSage SignalPilot.

Resolves a Kubernetes deployment revision to a git commit SHA,
diffs commits between prior and current revision, and identifies
suspect commits (likely contributors to the regression).

Data flow:
1. Read image tag from DeployChange.image_diffs[0].to_image
2. Try to resolve to commit SHA via:
   a. Pod template annotation: app.kubernetes.io/version
   b. Common labels: git-commit, git.sha, vcs-ref, version, sha, COMMIT_SHA
   c. If tag looks like a SHA (hex 7-40 chars), use it directly
   d. If tag looks like semver, try git tag lookup
3. Clone/open the repo (GitPython)
4. Diff from_sha → to_sha
5. Flag suspect commits: any commit that touches files matching
   SUSPECT_PATH_PATTERNS or has suspect commit messages
"""
from __future__ import annotations
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import git  # GitPython
from git import Repo, InvalidGitRepositoryError, GitCommandError

from signalpilot.models import CommitInfo, GitChange, DeployChange


# Annotations/labels to check for commit SHA (in priority order)
GIT_SHA_LABELS = [
    "app.kubernetes.io/version",
    "git-commit",
    "git.sha",
    "vcs-ref",
    "sha",
    "COMMIT_SHA",
    "GIT_COMMIT",
    "revision",
]

SHA_RE = re.compile(r"^[0-9a-f]{7,40}$", re.IGNORECASE)
SEMVER_RE = re.compile(r"^v?\d+\.\d+\.\d+")

# File path patterns that suggest high-impact changes
SUSPECT_PATH_PATTERNS = [
    re.compile(r"(?i)\.(py|go|java|js|ts|rb|cs|cpp|c|h)$"),    # source files
    re.compile(r"(?i)(Dockerfile|docker-compose|k8s|helm)"),     # infra changes
    re.compile(r"(?i)(config|settings|env|secret|credential)"),  # config changes
]

# Commit message keywords that suggest risky changes
SUSPECT_MESSAGE_PATTERNS = [
    re.compile(r"(?i)(fix|hotfix|patch|bug|critical|urgent|revert)"),
    re.compile(r"(?i)(performance|timeout|memory|cpu|cache|database|db)"),
    re.compile(r"(?i)(breaking|migration|upgrade|dependency|deps)"),
]


def resolve_commit_sha(
    image_tag: str,
    pod_annotations: dict[str, str],
    pod_labels: dict[str, str],
) -> Optional[str]:
    """
    Resolve a commit SHA from image tag and pod annotations/labels.

    Priority:
    1. Known git SHA labels in annotations (exact match for known keys)
    2. Known git SHA labels in labels
    3. If image_tag matches SHA_RE, use it directly
    4. If image_tag has a colon, check the part after colon
    5. Return None if unresolvable
    """
    for key in GIT_SHA_LABELS:
        for source in [pod_annotations, pod_labels]:
            val = source.get(key)
            if val and SHA_RE.match(val.strip()):
                return val.strip()

    tag = image_tag.split(":")[-1] if ":" in image_tag else image_tag
    if SHA_RE.match(tag):
        return tag

    return None


def diff_commits(
    repo_path: str,
    from_sha: Optional[str],
    to_sha: str,
) -> list[CommitInfo]:
    """
    Return commits between from_sha and to_sha (exclusive → inclusive).

    If from_sha is None, return the single commit at to_sha.
    Uses GitPython. Handles both local paths and remote URLs (clones if URL).

    Raises: InvalidGitRepositoryError if path is not a git repo.
    """
    repo = _open_or_clone(repo_path)

    if from_sha is None:
        try:
            commit = repo.commit(to_sha)
            return [_commit_to_info(commit)]
        except Exception:
            return []

    try:
        commits = list(repo.iter_commits(f"{from_sha}..{to_sha}"))
        return [_commit_to_info(c) for c in commits]
    except GitCommandError:
        return []


def flag_suspect_commits(commits: list[CommitInfo]) -> list[CommitInfo]:
    """
    Return subset of commits that are likely suspects.
    A commit is suspect if:
    - It changes source/infra/config files (SUSPECT_PATH_PATTERNS), OR
    - Its message matches SUSPECT_MESSAGE_PATTERNS
    """
    suspects = []
    for commit in commits:
        is_suspect = any(
            any(p.search(f) for p in SUSPECT_PATH_PATTERNS)
            for f in commit.files_changed
        ) or any(p.search(commit.message) for p in SUSPECT_MESSAGE_PATTERNS)
        if is_suspect:
            suspects.append(commit)
    return suspects


def build_git_change(
    repo_path: str,
    from_sha: Optional[str],
    to_sha: str,
    image_tag: str = "",
    pod_annotations: Optional[dict] = None,
    pod_labels: Optional[dict] = None,
) -> Optional[GitChange]:
    """
    Build a GitChange by opening repo_path and diffing from_sha → to_sha.

    Returns None if the repo can't be opened or SHAs can't be resolved.
    Degrades gracefully (does not raise).
    """
    if pod_annotations is None:
        pod_annotations = {}
    if pod_labels is None:
        pod_labels = {}

    resolved_to = to_sha
    if not resolved_to:
        resolved_to = resolve_commit_sha(image_tag, pod_annotations, pod_labels)
    if not resolved_to:
        return None

    try:
        commits = diff_commits(repo_path, from_sha, resolved_to)
    except Exception:
        return None

    suspects = flag_suspect_commits(commits)
    suspect_files = list({f for c in suspects for f in c.files_changed})

    return GitChange(
        repo=repo_path,
        from_sha=from_sha,
        to_sha=resolved_to,
        commits=commits,
        suspect_commits=suspects,
        suspect_files=suspect_files,
    )


def enrich_deploy_change(
    deploy_change: DeployChange,
    repo_path: str,
    pod_annotations: Optional[dict] = None,
    pod_labels: Optional[dict] = None,
) -> DeployChange:
    """
    Add GitChange to a DeployChange by resolving commit SHAs and diffing.

    Uses image tag from first image_diff as the to_sha hint.
    Uses from_revision and to_revision as SHA hints if they look like SHAs.

    Returns a new DeployChange with .git populated (or unchanged if no repo).
    """
    pod_annotations = pod_annotations or {}
    pod_labels = pod_labels or {}

    to_sha = ""
    if deploy_change.image_diffs:
        tag = deploy_change.image_diffs[0].to_image.split(":")[-1]
        if SHA_RE.match(tag):
            to_sha = tag

    if not to_sha:
        to_sha = resolve_commit_sha("", pod_annotations, pod_labels) or ""
    if not to_sha and SHA_RE.match(deploy_change.to_revision or ""):
        to_sha = deploy_change.to_revision or ""

    if not to_sha:
        return deploy_change

    from_sha = None
    if SHA_RE.match(deploy_change.from_revision or ""):
        from_sha = deploy_change.from_revision

    git_change = build_git_change(repo_path, from_sha, to_sha)
    if git_change is None:
        return deploy_change

    return deploy_change.model_copy(update={"git": git_change})


def _open_or_clone(repo_path: str) -> Repo:
    """Open a local repo or clone a remote URL to a temp dir."""
    if repo_path.startswith(("http://", "https://", "git@", "ssh://")):
        import tempfile
        tmp = tempfile.mkdtemp(prefix="signalpilot_git_")
        return Repo.clone_from(repo_path, tmp, depth=50)
    return Repo(repo_path)


def _commit_to_info(commit) -> CommitInfo:
    """Convert a GitPython Commit to CommitInfo."""
    files_changed = []
    try:
        if commit.parents:
            diff = commit.parents[0].diff(commit)
            files_changed = [d.a_path or d.b_path for d in diff]
        else:
            files_changed = list(commit.stats.files.keys())[:50]
    except Exception:
        pass

    return CommitInfo(
        sha=commit.hexsha[:12],
        author=str(commit.author.email or commit.author.name),
        message=commit.message.strip()[:200],
        files_changed=files_changed[:100],
        ts=datetime.fromtimestamp(commit.committed_date, tz=timezone.utc),
    )
