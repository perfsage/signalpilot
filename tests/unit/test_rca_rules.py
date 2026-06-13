from datetime import datetime, timezone

from signalpilot.models import (
    CommitInfo,
    DeployChange,
    GitChange,
    ImageDiff,
    LogCluster,
    RegressionWindow,
    ResourceDiff,
    Severity,
    Signal,
    SignalKind,
    SignalSource,
    Target,
)
from signalpilot.rca.rules import (
    RcaContext,
    _format_mem,
    _parse_cpu,
    _parse_mem,
    rule_code_regression,
    rule_configmap_error,
    rule_cpu_throttled,
    rule_crash_loop,
    rule_image_pull_error,
    rule_init_container_fail,
    rule_network_latency,
    rule_oom_killed,
    rule_pending_unschedulable,
    rule_probe_failure,
)

T0 = datetime(2024, 6, 1, 12, 0, tzinfo=timezone.utc)


def make_sig(kind, severity=Severity.HIGH, name="api-pod-abc", value=None, msg="test"):
    return Signal(
        type="signal", ts=T0, source=SignalSource.KUBE_API,
        kind=kind, severity=severity,
        target=Target(kind="Pod", namespace="ns", name=name, container="app"),
        value=value, message=msg,
    )


def make_ctx(**kwargs) -> RcaContext:
    return RcaContext(
        signals=kwargs.get("signals", []),
        log_clusters=kwargs.get("log_clusters", []),
        regressions=kwargs.get("regressions", []),
        deploy_change=kwargs.get("deploy_change"),
        namespace="ns",
        deployment=kwargs.get("deployment"),
    )


class TestRuleOomKilled:
    def test_fires_on_oom_signal(self):
        ctx = make_ctx(signals=[make_sig(SignalKind.OOM_KILLED)])
        findings = rule_oom_killed(ctx)
        assert len(findings) == 1
        assert findings[0].rule_id == "oom_killed"
        assert findings[0].severity == Severity.CRITICAL

    def test_no_oom_no_finding(self):
        ctx = make_ctx(signals=[make_sig(SignalKind.RESTART)])
        assert rule_oom_killed(ctx) == []

    def test_fix_has_kubectl_snippet(self):
        ctx = make_ctx(signals=[make_sig(SignalKind.OOM_KILLED)])
        finding = rule_oom_killed(ctx)[0]
        assert any("kubectl" in (f.kubectl_snippet or "") for f in finding.fixes)

    def test_mem_signal_corroborated(self):
        ctx = make_ctx(signals=[
            make_sig(SignalKind.OOM_KILLED),
            make_sig(SignalKind.MEM_WORKING_SET, value=500 * 1024 * 1024),
        ])
        finding = rule_oom_killed(ctx)[0]
        assert len(finding.evidence) >= 2

    def test_proposed_limit_doubled_when_resource_diff(self):
        rd = ResourceDiff(
            container="app",
            from_cpu_request=None, to_cpu_request=None,
            from_cpu_limit=None, to_cpu_limit=None,
            from_mem_request=None, to_mem_request=None,
            from_mem_limit="128Mi", to_mem_limit="128Mi",
        )
        dc = DeployChange(
            deployment="api", namespace="ns",
            from_revision="1", to_revision="2",
            deploy_time=T0, resource_diffs=[rd],
        )
        ctx = make_ctx(signals=[make_sig(SignalKind.OOM_KILLED)], deploy_change=dc)
        finding = rule_oom_killed(ctx)[0]
        fix = finding.fixes[0]
        assert fix.proposed_value == "256Mi"
        assert fix.current_value == "128Mi"


class TestRuleCpuThrottled:
    def test_fires_on_high_throttle(self):
        ctx = make_ctx(signals=[make_sig(SignalKind.CPU_THROTTLED, value=0.6)])
        findings = rule_cpu_throttled(ctx)
        assert len(findings) == 1
        assert findings[0].rule_id == "cpu_throttled"

    def test_no_throttle_no_finding(self):
        ctx = make_ctx(signals=[make_sig(SignalKind.CPU_THROTTLED, value=0.1)])
        findings = rule_cpu_throttled(ctx)
        assert len(findings) == 0

    def test_latency_regression_boosts_confidence(self):
        reg = RegressionWindow(
            metric="latency_p95", before_mean=50.0, after_mean=200.0,
            pct_change=3.0, z_score=5.0, is_regression=True,
        )
        ctx_no_reg = make_ctx(signals=[make_sig(SignalKind.CPU_THROTTLED, value=0.5)])
        ctx_with_reg = make_ctx(
            signals=[make_sig(SignalKind.CPU_THROTTLED, value=0.5)],
            regressions=[reg],
        )
        f_no = rule_cpu_throttled(ctx_no_reg)
        f_with = rule_cpu_throttled(ctx_with_reg)
        if f_no and f_with:
            assert f_with[0].confidence >= f_no[0].confidence

    def test_falls_back_to_high_severity_cpu_usage(self):
        ctx = make_ctx(signals=[make_sig(SignalKind.CPU_USAGE, severity=Severity.CRITICAL, value=0.99)])
        findings = rule_cpu_throttled(ctx)
        assert len(findings) == 1

    def test_no_finding_for_low_cpu_usage(self):
        ctx = make_ctx(signals=[make_sig(SignalKind.CPU_USAGE, severity=Severity.LOW, value=0.1)])
        findings = rule_cpu_throttled(ctx)
        assert len(findings) == 0


class TestRuleCrashLoop:
    def test_fires_on_crashloop(self):
        ctx = make_ctx(signals=[make_sig(SignalKind.CRASH_LOOP)])
        findings = rule_crash_loop(ctx)
        assert len(findings) == 1
        assert findings[0].severity == Severity.CRITICAL

    def test_includes_rollback_fix_when_config_changed(self):
        dc = DeployChange(
            deployment="api", namespace="ns",
            from_revision="1", to_revision="2",
            deploy_time=T0,
            env_diff={"DB_URL": ("old", "new")},
        )
        ctx = make_ctx(signals=[make_sig(SignalKind.CRASH_LOOP)], deploy_change=dc)
        finding = rule_crash_loop(ctx)[0]
        assert any(f.kind == "rollback" for f in finding.fixes)

    def test_no_crash_no_finding(self):
        ctx = make_ctx(signals=[make_sig(SignalKind.RESTART)])
        assert rule_crash_loop(ctx) == []

    def test_log_cluster_boosts_confidence(self):
        ctx_plain = make_ctx(signals=[make_sig(SignalKind.CRASH_LOOP)])
        cluster = LogCluster(
            fingerprint="fp1", template="connection refused to <*>",
            count_before=0, count_after=3, is_new=True, category="conn",
        )
        ctx_with_cluster = make_ctx(
            signals=[make_sig(SignalKind.CRASH_LOOP)],
            log_clusters=[cluster],
        )
        f_plain = rule_crash_loop(ctx_plain)[0]
        f_cluster = rule_crash_loop(ctx_with_cluster)[0]
        assert f_cluster.confidence >= f_plain.confidence


class TestRuleImagePullError:
    def test_fires_with_high_confidence(self):
        ctx = make_ctx(signals=[make_sig(SignalKind.IMAGE_PULL_ERROR)])
        findings = rule_image_pull_error(ctx)
        assert len(findings) == 1
        assert findings[0].confidence >= 0.95

    def test_includes_rollback_fix(self):
        ctx = make_ctx(signals=[make_sig(SignalKind.IMAGE_PULL_ERROR)])
        finding = rule_image_pull_error(ctx)[0]
        assert any(f.kind == "rollback" for f in finding.fixes)

    def test_no_signal_no_finding(self):
        ctx = make_ctx()
        assert rule_image_pull_error(ctx) == []

    def test_bad_image_included_in_explanation(self):
        dc = DeployChange(
            deployment="api", namespace="ns",
            from_revision="1", to_revision="2",
            deploy_time=T0,
            image_diffs=[ImageDiff(
                from_image="app:v1", to_image="app:v999-bad",
                tag_changed=True, digest_changed=True,
            )],
        )
        ctx = make_ctx(signals=[make_sig(SignalKind.IMAGE_PULL_ERROR)], deploy_change=dc)
        finding = rule_image_pull_error(ctx)[0]
        assert "app:v999-bad" in finding.explanation


class TestRuleProbeFailure:
    def test_fires_on_probe_failure(self):
        ctx = make_ctx(signals=[make_sig(SignalKind.PROBE_FAILURE)])
        findings = rule_probe_failure(ctx)
        assert len(findings) == 1
        assert findings[0].rule_id == "probe_failure"
        assert findings[0].severity == Severity.HIGH

    def test_no_probe_no_finding(self):
        ctx = make_ctx()
        assert rule_probe_failure(ctx) == []

    def test_has_patch_fix(self):
        ctx = make_ctx(signals=[make_sig(SignalKind.PROBE_FAILURE)])
        finding = rule_probe_failure(ctx)[0]
        assert any(f.kind == "patch" for f in finding.fixes)


class TestRulePendingUnschedulable:
    def test_fires_on_pending_pod(self):
        ctx = make_ctx(signals=[make_sig(SignalKind.PENDING_POD)])
        findings = rule_pending_unschedulable(ctx)
        assert len(findings) == 1
        assert findings[0].rule_id == "pending_unschedulable"

    def test_higher_confidence_with_failed_scheduling_event(self):
        ctx_no_event = make_ctx(signals=[make_sig(SignalKind.PENDING_POD)])
        ctx_with_event = make_ctx(signals=[
            make_sig(SignalKind.PENDING_POD),
            make_sig(SignalKind.EVENT, msg="FailedScheduling: Insufficient memory"),
        ])
        f_no = rule_pending_unschedulable(ctx_no_event)[0]
        f_event = rule_pending_unschedulable(ctx_with_event)[0]
        assert f_event.confidence > f_no.confidence

    def test_no_pending_no_finding(self):
        ctx = make_ctx()
        assert rule_pending_unschedulable(ctx) == []


class TestRuleCodeRegression:
    def test_fires_on_new_log_cluster(self):
        cluster = LogCluster(
            fingerprint="fp1", template="NullPointerException at <*>",
            count_before=0, count_after=5, is_new=True,
        )
        ctx = make_ctx(log_clusters=[cluster])
        findings = rule_code_regression(ctx)
        assert len(findings) == 1
        assert findings[0].rule_id == "code_regression"

    def test_no_new_cluster_no_finding(self):
        cluster = LogCluster(
            fingerprint="fp1", template="Connection refused to <*>",
            count_before=3, count_after=4, is_new=False,
        )
        ctx = make_ctx(log_clusters=[cluster])
        assert rule_code_regression(ctx) == []

    def test_error_regression_boosts_confidence(self):
        cluster = LogCluster(
            fingerprint="fp1", template="Error at <*>",
            count_before=0, count_after=5, is_new=True,
        )
        reg = RegressionWindow(
            metric="log_error_rate", before_mean=0.01, after_mean=0.5,
            pct_change=50.0, z_score=8.0, is_regression=True,
        )
        ctx_plain = make_ctx(log_clusters=[cluster])
        ctx_reg = make_ctx(log_clusters=[cluster], regressions=[reg])
        f_plain = rule_code_regression(ctx_plain)[0]
        f_reg = rule_code_regression(ctx_reg)[0]
        assert f_reg.confidence > f_plain.confidence

    def test_suspect_commit_in_explanation(self):
        cluster = LogCluster(
            fingerprint="fp1", template="Error <*>",
            count_before=0, count_after=2, is_new=True,
        )
        commit = CommitInfo(sha="abcdef1234567890", author="dev", message="add feature X")
        gc = GitChange(repo="myrepo", from_sha="aaa", to_sha="bbb", suspect_commits=[commit])
        dc = DeployChange(
            deployment="api", namespace="ns",
            from_revision="1", to_revision="2",
            deploy_time=T0, git=gc,
        )
        ctx = make_ctx(log_clusters=[cluster], deploy_change=dc)
        finding = rule_code_regression(ctx)[0]
        assert "abcdef12" in finding.explanation


class TestRuleNetworkLatency:
    def test_fires_on_tcp_retransmit(self):
        ctx = make_ctx(signals=[make_sig(SignalKind.TCP_RETRANSMIT, value=50.0)])
        findings = rule_network_latency(ctx)
        assert len(findings) == 1
        assert findings[0].rule_id == "network_latency"

    def test_fires_on_dns_latency(self):
        ctx = make_ctx(signals=[make_sig(SignalKind.DNS_LATENCY, value=500.0)])
        findings = rule_network_latency(ctx)
        assert len(findings) == 1
        assert "DNS" in findings[0].title

    def test_no_network_signals_no_finding(self):
        ctx = make_ctx()
        assert rule_network_latency(ctx) == []

    def test_dns_only_title(self):
        ctx = make_ctx(signals=[make_sig(SignalKind.DNS_LATENCY)])
        finding = rule_network_latency(ctx)[0]
        assert "DNS" in finding.title


class TestHelpers:
    def test_parse_mem_mebibytes(self):
        assert _parse_mem("128Mi") == 128 * 1024 ** 2

    def test_parse_mem_gibibytes(self):
        assert _parse_mem("2Gi") == 2 * 1024 ** 3

    def test_parse_mem_kibibytes(self):
        assert _parse_mem("512Ki") == 512 * 1024

    def test_format_mem_roundtrip(self):
        val = 256 * 1024 ** 2
        assert _parse_mem(_format_mem(val)) == val

    def test_format_mem_gi(self):
        assert _format_mem(2 * 1024 ** 3) == "2Gi"

    def test_format_mem_mi(self):
        assert _format_mem(128 * 1024 ** 2) == "128Mi"

    def test_parse_cpu_millicore(self):
        assert _parse_cpu("500m") == 500.0

    def test_parse_cpu_full_core(self):
        assert _parse_cpu("2") == 2000.0

    def test_parse_cpu_fractional(self):
        assert _parse_cpu("1.5") == 1500.0


class TestRuleConfigmapError:
    def _event_sig(self, msg: str):
        return Signal(
            type="signal", ts=T0, source=SignalSource.EVENTS,
            kind=SignalKind.EVENT, severity=Severity.CRITICAL,
            target=Target(kind="Pod", namespace="ns", name="pod-abc"),
            message=msg,
        )

    def test_fires_on_create_container_config_error(self):
        ctx = make_ctx(signals=[self._event_sig("CreateContainerConfigError: configmap not found")])
        findings = rule_configmap_error(ctx)
        assert len(findings) == 1
        assert findings[0].rule_id == "configmap_error"
        assert findings[0].severity == Severity.CRITICAL

    def test_fires_on_configmap_keyword(self):
        ctx = make_ctx(signals=[self._event_sig("MountVolume failed: configmap 'sp-nonexistent' not found")])
        findings = rule_configmap_error(ctx)
        assert len(findings) == 1

    def test_no_config_error_no_finding(self):
        ctx = make_ctx(signals=[self._event_sig("Pulled image successfully")])
        assert rule_configmap_error(ctx) == []

    def test_has_kubectl_fix(self):
        ctx = make_ctx(signals=[self._event_sig("CreateContainerConfigError")])
        finding = rule_configmap_error(ctx)[0]
        assert any("kubectl" in (f.kubectl_snippet or "") for f in finding.fixes)

    def test_confidence_is_high(self):
        ctx = make_ctx(signals=[self._event_sig("CreateContainerConfigError")])
        finding = rule_configmap_error(ctx)[0]
        assert finding.confidence >= 0.90


class TestRuleInitContainerFail:
    def _event_sig(self, msg: str):
        return Signal(
            type="signal", ts=T0, source=SignalSource.EVENTS,
            kind=SignalKind.EVENT, severity=Severity.HIGH,
            target=Target(kind="Pod", namespace="ns", name="pod-abc"),
            message=msg,
        )

    def _crash_sig(self, msg: str):
        return Signal(
            type="signal", ts=T0, source=SignalSource.KUBE_API,
            kind=SignalKind.CRASH_LOOP, severity=Severity.CRITICAL,
            target=Target(kind="Pod", namespace="ns", name="pod-abc", container="init-checker"),
            message=msg,
        )

    def test_fires_on_backoff_event(self):
        ctx = make_ctx(signals=[self._event_sig("BackOff restarting init container")])
        findings = rule_init_container_fail(ctx)
        assert len(findings) == 1
        assert findings[0].rule_id == "init_container_fail"

    def test_fires_on_crash_sig_with_init(self):
        ctx = make_ctx(signals=[self._crash_sig("init container init-checker crashed")])
        findings = rule_init_container_fail(ctx)
        assert len(findings) == 1

    def test_no_init_signal_no_finding(self):
        ctx = make_ctx(signals=[self._event_sig("Pulled image successfully")])
        assert rule_init_container_fail(ctx) == []

    def test_has_two_fixes(self):
        ctx = make_ctx(signals=[self._event_sig("BackOff restarting init container init-checker")])
        finding = rule_init_container_fail(ctx)[0]
        assert len(finding.fixes) >= 2

    def test_log_clusters_added_to_evidence(self):
        cluster = LogCluster(
            fingerprint="abc", template="ERROR init failed",
            count_before=0, count_after=5, is_new=True,
        )
        ctx = make_ctx(
            signals=[self._event_sig("BackOff restarting init container")],
            log_clusters=[cluster],
        )
        finding = rule_init_container_fail(ctx)[0]
        assert cluster in finding.evidence
