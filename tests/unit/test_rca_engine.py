from datetime import datetime, timezone

from signalpilot.models import LogCluster, Severity, Signal, SignalKind, SignalSource, Target
from signalpilot.rca.engine import RcaEngine

T0 = datetime(2024, 6, 1, 12, 0, tzinfo=timezone.utc)


def make_sig(kind, severity=Severity.HIGH):
    return Signal(
        type="signal", ts=T0, source=SignalSource.KUBE_API,
        kind=kind, severity=severity,
        target=Target(kind="Pod", namespace="ns", name="api-abc"),
        message="test", value=1.0,
    )


class TestRcaEngine:
    def test_oom_scenario_top_finding(self):
        engine = RcaEngine()
        analysis = engine.analyze(
            namespace="ns",
            signals=[make_sig(SignalKind.OOM_KILLED, Severity.CRITICAL)],
        )
        assert len(analysis.findings) > 0
        assert analysis.findings[0].rule_id == "oom_killed"

    def test_no_signals_no_findings(self):
        engine = RcaEngine()
        analysis = engine.analyze(namespace="ns", signals=[])
        assert analysis.findings == []

    def test_multiple_rules_ranked(self):
        engine = RcaEngine()
        analysis = engine.analyze(
            namespace="ns",
            signals=[
                make_sig(SignalKind.OOM_KILLED, Severity.CRITICAL),
                make_sig(SignalKind.PROBE_FAILURE, Severity.HIGH),
            ],
        )
        ids = [f.rule_id for f in analysis.findings]
        assert ids.index("oom_killed") < ids.index("probe_failure")

    def test_analysis_has_metadata(self):
        engine = RcaEngine()
        analysis = engine.analyze(namespace="ns", signals=[make_sig(SignalKind.RESTART)])
        assert analysis.id
        assert analysis.ts
        assert analysis.duration_s is not None

    def test_rule_exception_does_not_crash_engine(self):
        engine = RcaEngine()

        def broken_rule(ctx):
            raise RuntimeError("rule failed")

        engine._rules.append(broken_rule)
        analysis = engine.analyze(namespace="ns", signals=[])
        assert analysis is not None

    def test_log_cluster_finding(self):
        engine = RcaEngine()
        cluster = LogCluster(
            fingerprint="fp1", template="NullPointerException at <*>",
            count_before=0, count_after=10, is_new=True,
        )
        analysis = engine.analyze(namespace="ns", signals=[], log_clusters=[cluster])
        code_findings = [f for f in analysis.findings if f.rule_id == "code_regression"]
        assert len(code_findings) > 0

    def test_analysis_namespace_preserved(self):
        engine = RcaEngine()
        analysis = engine.analyze(namespace="production", signals=[])
        assert analysis.namespace == "production"

    def test_sources_used_forwarded(self):
        engine = RcaEngine()
        analysis = engine.analyze(
            namespace="ns", signals=[],
            sources_used=["kube_api", "prometheus"],
        )
        assert "kube_api" in analysis.sources_used
        assert "prometheus" in analysis.sources_used

    def test_critical_outranks_high(self):
        engine = RcaEngine()
        analysis = engine.analyze(
            namespace="ns",
            signals=[
                make_sig(SignalKind.IMAGE_PULL_ERROR, Severity.CRITICAL),
                make_sig(SignalKind.PROBE_FAILURE, Severity.HIGH),
            ],
        )
        rules = [f.rule_id for f in analysis.findings]
        assert rules.index("image_pull_error") < rules.index("probe_failure")

    def test_duration_is_positive(self):
        engine = RcaEngine()
        analysis = engine.analyze(namespace="ns", signals=[])
        assert analysis.duration_s >= 0.0
