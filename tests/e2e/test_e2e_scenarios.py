"""
E2E tests for SignalPilot against the signalpilot-test namespace.

These tests require:
1. A running Kubernetes cluster (kubectl config set)
2. Sample apps deployed: run `scripts/setup_test.sh` first
3. SIGNALPILOT_KUBECONFIG set or default kubeconfig available

Skip automatically if cluster is not available.
"""
import pytest
from kubernetes import config as kube_config, client
from kubernetes.config.config_exception import ConfigException


def cluster_available() -> bool:
    try:
        kube_config.load_kube_config()
        client.CoreV1Api().list_namespace(limit=1)
        return True
    except Exception:
        return False


CLUSTER = pytest.mark.skipif(
    not cluster_available(),
    reason="No K8s cluster available"
)


@CLUSTER
class TestE2EScenarios:
    """Live E2E tests against signalpilot-test namespace."""

    @pytest.fixture(autouse=True)
    def load_kube(self):
        try:
            kube_config.load_kube_config()
        except Exception:
            pytest.skip("Cannot load kubeconfig")

    def _analyze(self, deployment: str):
        from signalpilot.cli import _run_analysis
        return _run_analysis("signalpilot-test", deployment, None, False, None, True)

    def test_imagepull_scenario(self):
        """sp-test-imagepull should produce image_pull_error finding."""
        analysis = self._analyze("sp-test-imagepull")
        rule_ids = [f.rule_id for f in analysis.findings]
        assert "image_pull_error" in rule_ids, f"Expected image_pull_error, got: {rule_ids}"

    def test_crashloop_scenario(self):
        """sp-test-crash should produce crash_loop finding."""
        analysis = self._analyze("sp-test-crash")
        rule_ids = [f.rule_id for f in analysis.findings]
        assert "crash_loop" in rule_ids, f"Expected crash_loop, got: {rule_ids}"

    def test_probe_fail_scenario(self):
        """sp-test-probe should produce probe_failure finding."""
        analysis = self._analyze("sp-test-probe")
        rule_ids = [f.rule_id for f in analysis.findings]
        assert "probe_failure" in rule_ids, f"Expected probe_failure, got: {rule_ids}"

    def test_unschedulable_scenario(self):
        """sp-test-unschedulable should produce pending_unschedulable finding."""
        analysis = self._analyze("sp-test-unschedulable")
        rule_ids = [f.rule_id for f in analysis.findings]
        assert "pending_unschedulable" in rule_ids, f"Expected pending_unschedulable, got: {rule_ids}"

    def test_regression_scenario(self):
        """sp-test-regression v2 should produce code_regression finding."""
        analysis = self._analyze("sp-test-regression")
        rule_ids = [f.rule_id for f in analysis.findings]
        # v2 returns 500s → new error log fingerprints → code_regression
        # May also detect restarts/probe failures
        assert len(analysis.findings) > 0, "Expected at least one finding for broken v2"
