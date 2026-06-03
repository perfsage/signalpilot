from pathlib import Path
from datetime import datetime, timezone

from signalpilot.verification.store import VerificationStore
from signalpilot.models import Analysis, Finding, Fix, Target, Severity

T0 = datetime(2024, 6, 1, tzinfo=timezone.utc)


def make_analysis(id_: str = "a1", findings: list | None = None) -> Analysis:
    return Analysis(
        id=id_,
        ts=T0,
        namespace="ns",
        findings=findings or [],
        sources_used=[],
        deploy_change=None,
    )


def make_finding(
    rule_id: str = "oom_killed",
    name: str = "pod1",
    sev: Severity = Severity.HIGH,
) -> Finding:
    return Finding(
        id="f1",
        title=f"Test {rule_id}",
        severity=sev,
        confidence=0.9,
        blast_radius=0.1,
        target=Target(kind="Pod", namespace="ns", name=name),
        explanation="test",
        rule_id=rule_id,
    )


class TestVerificationStore:
    def test_save_and_load(self, tmp_path: Path) -> None:
        store = VerificationStore(tmp_path)
        analysis = make_analysis()
        path = store.save(analysis)
        assert path.exists()
        loaded = store.load("a1")
        assert loaded is not None
        assert loaded.id == "a1"

    def test_load_nonexistent_returns_none(self, tmp_path: Path) -> None:
        store = VerificationStore(tmp_path)
        assert store.load("nonexistent") is None

    def test_list_analyses(self, tmp_path: Path) -> None:
        store = VerificationStore(tmp_path)
        store.save(make_analysis("a1"))
        store.save(make_analysis("a2"))
        ids = store.list_analyses()
        assert "a1" in ids
        assert "a2" in ids

    def test_compare_fixed_finding(self, tmp_path: Path) -> None:
        store = VerificationStore(tmp_path)
        baseline = make_analysis("b1", [make_finding("oom_killed")])
        current = make_analysis("c1", [])
        result = store.compare(baseline, current)
        assert "Fixed" in result
        assert "oom_killed" in result or "Test oom_killed" in result

    def test_compare_new_regression(self, tmp_path: Path) -> None:
        store = VerificationStore(tmp_path)
        baseline = make_analysis("b1", [])
        current = make_analysis("c1", [make_finding("crash_loop")])
        result = store.compare(baseline, current)
        assert "Regressed" in result or "New" in result

    def test_compare_unchanged(self, tmp_path: Path) -> None:
        store = VerificationStore(tmp_path)
        f = make_finding("probe_failure")
        baseline = make_analysis("b1", [f])
        current = make_analysis("c1", [f])
        result = store.compare(baseline, current)
        assert "Unchanged" in result

    def test_save_and_load_by_revision(self, tmp_path: Path) -> None:
        store = VerificationStore(tmp_path)
        analysis = make_analysis("rev_test")
        store.save_by_revision(analysis, "v42")
        loaded = store.load_by_revision("v42")
        assert loaded is not None

    def test_compare_no_changes(self, tmp_path: Path) -> None:
        store = VerificationStore(tmp_path)
        baseline = make_analysis("b1", [])
        current = make_analysis("c1", [])
        result = store.compare(baseline, current)
        assert "No changes" in result

    def test_list_empty(self, tmp_path: Path) -> None:
        store = VerificationStore(tmp_path)
        assert store.list_analyses() == []

    def test_load_by_revision_nonexistent(self, tmp_path: Path) -> None:
        store = VerificationStore(tmp_path)
        assert store.load_by_revision("v999") is None
