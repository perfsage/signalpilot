import os
import pytest
from pathlib import Path
from signalpilot.collectors.git import (
    resolve_commit_sha,
    flag_suspect_commits,
    build_git_change,
    diff_commits,
    _commit_to_info,
)
from signalpilot.models import CommitInfo

REPO_ROOT = str(Path(__file__).parent.parent.parent)  # /Users/aashu/Documents/SignalPilot


class TestResolveCommitSha:
    def test_annotation_takes_priority(self):
        result = resolve_commit_sha(
            "myapp:v1.0.0",
            {"git-commit": "abc1234def5678901234567890123456789012ab"},
            {},
        )
        assert result == "abc1234def5678901234567890123456789012ab"

    def test_image_tag_sha_fallback(self):
        result = resolve_commit_sha("myapp:abc1234def56", {}, {})
        assert result == "abc1234def56"

    def test_semver_tag_not_sha(self):
        result = resolve_commit_sha("myapp:v1.2.3", {}, {})
        assert result is None

    def test_label_fallback(self):
        result = resolve_commit_sha(
            "myapp:latest",
            {},
            {"git.sha": "deadbeef1234"},
        )
        assert result == "deadbeef1234"


class TestFlagSuspectCommits:
    def test_source_file_change_is_suspect(self):
        commit = CommitInfo(
            sha="abc1234", author="dev@test.com",
            message="add feature", files_changed=["src/handler.py"]
        )
        suspects = flag_suspect_commits([commit])
        assert len(suspects) == 1

    def test_fix_message_is_suspect(self):
        commit = CommitInfo(
            sha="abc1234", author="dev@test.com",
            message="fix: critical bug in payment handler", files_changed=[]
        )
        suspects = flag_suspect_commits([commit])
        assert len(suspects) == 1

    def test_readme_only_not_suspect(self):
        commit = CommitInfo(
            sha="abc1234", author="dev@test.com",
            message="update readme", files_changed=["README.md"]
        )
        suspects = flag_suspect_commits([commit])
        assert len(suspects) == 0

    def test_multiple_commits_filtered(self):
        commits = [
            CommitInfo(sha="a1", author="a@b.com", message="update readme", files_changed=["README.md"]),
            CommitInfo(sha="a2", author="a@b.com", message="fix memory leak", files_changed=["src/cache.py"]),
        ]
        suspects = flag_suspect_commits(commits)
        assert len(suspects) == 1
        assert suspects[0].sha == "a2"


class TestDiffCommits:
    def test_own_repo_has_commits(self):
        """Use SignalPilot's own git repo — should have at least 1 commit."""
        commits = diff_commits(REPO_ROOT, None, "HEAD")
        assert len(commits) >= 1
        assert all(isinstance(c, CommitInfo) for c in commits)

    def test_sha_range_returns_subset(self):
        """Get first 2 commits to test range diffing."""
        all_commits = diff_commits(REPO_ROOT, None, "HEAD")
        if len(all_commits) < 2:
            pytest.skip("Need at least 2 commits")
        second_to_last = all_commits[-1].sha
        head = all_commits[0].sha
        subset = diff_commits(REPO_ROOT, second_to_last, head)
        assert len(subset) < len(all_commits)

    def test_invalid_repo_raises(self):
        with pytest.raises(Exception):
            diff_commits("/tmp/not-a-git-repo", None, "HEAD")

    def test_commit_info_has_required_fields(self):
        commits = diff_commits(REPO_ROOT, None, "HEAD")
        for c in commits:
            assert c.sha
            assert c.author
            assert c.message
