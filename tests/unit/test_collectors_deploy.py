"""Unit tests for deploy.py get_deploy_change() using recorded fixture data."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from signalpilot.collectors.deploy import (
    get_deploy_change,
    _diff_images,
    _diff_env,
    _diff_resources,
    _mask_env_value,
)
from signalpilot.models import DeployChange

from tests.unit.conftest_k8s import make_rs_list, ns

FIXTURES = Path(__file__).parent.parent / "fixtures" / "k8s"


def load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text())


def _make_apis(rs_data: dict) -> tuple[MagicMock, MagicMock]:
    mock_apps = MagicMock()
    mock_apps.read_namespaced_deployment.return_value = MagicMock()
    mock_apps.list_namespaced_replica_set.return_value = make_rs_list(rs_data)
    return mock_apps


class TestMaskEnvValue:
    def test_password_masked(self):
        assert _mask_env_value("DB_PASSWORD", "hunter2") == "[REDACTED]"

    def test_token_masked(self):
        assert _mask_env_value("API_TOKEN", "abc123") == "[REDACTED]"

    def test_secret_masked(self):
        assert _mask_env_value("MY_SECRET", "shh") == "[REDACTED]"

    def test_api_key_masked(self):
        assert _mask_env_value("API_KEY", "key123") == "[REDACTED]"

    def test_normal_env_not_masked(self):
        assert _mask_env_value("LOG_LEVEL", "DEBUG") == "DEBUG"

    def test_db_host_not_masked(self):
        assert _mask_env_value("DB_HOST", "postgres:5432") == "postgres:5432"


class TestDiffImages:
    def test_image_change_detected(self):
        prev = [ns({"name": "app", "image": "repo/app:v1.0.0"})]
        curr = [ns({"name": "app", "image": "repo/app:v1.1.0"})]
        diffs = _diff_images(prev, curr)
        assert len(diffs) == 1
        assert diffs[0].from_image == "repo/app:v1.0.0"
        assert diffs[0].to_image == "repo/app:v1.1.0"
        assert diffs[0].tag_changed is True

    def test_no_change_returns_empty(self):
        prev = [ns({"name": "app", "image": "repo/app:v1.0.0"})]
        curr = [ns({"name": "app", "image": "repo/app:v1.0.0"})]
        assert _diff_images(prev, curr) == []

    def test_digest_changed_flag(self):
        prev = [ns({"name": "app", "image": "repo/app:latest@sha256:aaa"})]
        curr = [ns({"name": "app", "image": "repo/app:latest@sha256:bbb"})]
        diffs = _diff_images(prev, curr)
        assert diffs[0].digest_changed is True


class TestDiffEnv:
    def test_env_change_detected(self):
        prev = [ns({"name": "app", "env": [{"name": "LOG_LEVEL", "value": "INFO"}]})]
        curr = [ns({"name": "app", "env": [{"name": "LOG_LEVEL", "value": "DEBUG"}]})]
        diff = _diff_env(prev, curr)
        assert "LOG_LEVEL" in diff
        assert diff["LOG_LEVEL"] == ("INFO", "DEBUG")

    def test_added_env_var_detected(self):
        prev = [ns({"name": "app", "env": [{"name": "LOG_LEVEL", "value": "INFO"}]})]
        curr = [ns({"name": "app", "env": [
            {"name": "LOG_LEVEL", "value": "INFO"},
            {"name": "NEW_VAR", "value": "newvalue"},
        ]})]
        diff = _diff_env(prev, curr)
        assert "NEW_VAR" in diff

    def test_password_value_masked_in_diff(self):
        prev = [ns({"name": "app", "env": [{"name": "DB_PASSWORD", "value": "old123"}]})]
        curr = [ns({"name": "app", "env": [{"name": "DB_PASSWORD", "value": "new456"}]})]
        diff = _diff_env(prev, curr)
        assert "DB_PASSWORD" in diff
        # Both sides should be masked
        assert diff["DB_PASSWORD"] == ("[REDACTED]", "[REDACTED]")

    def test_no_change_returns_empty(self):
        prev = [ns({"name": "app", "env": [{"name": "LOG_LEVEL", "value": "INFO"}]})]
        curr = [ns({"name": "app", "env": [{"name": "LOG_LEVEL", "value": "INFO"}]})]
        assert _diff_env(prev, curr) == {}


class TestGetDeployChange:
    def _call(self, rs_data: dict) -> DeployChange | None:
        mock_apps = _make_apis(rs_data)
        with patch("signalpilot.collectors.deploy._load_kube_config"), \
             patch("signalpilot.collectors.deploy.client") as mock_client:
            mock_client.AppsV1Api.return_value = mock_apps
            result = get_deploy_change("default", "api-server", settings=None)
        return result

    def test_returns_deploy_change(self):
        result = self._call(load("replicasets.json"))
        assert isinstance(result, DeployChange)

    def test_revisions_populated(self):
        result = self._call(load("replicasets.json"))
        assert result.from_revision == "1"
        assert result.to_revision == "2"

    def test_image_diff_detected(self):
        result = self._call(load("replicasets.json"))
        assert len(result.image_diffs) > 0
        assert result.image_diffs[0].from_image == "myrepo/api-server:v1.0.0"
        assert result.image_diffs[0].to_image == "myrepo/api-server:v1.1.0"

    def test_tag_changed(self):
        result = self._call(load("replicasets.json"))
        assert result.image_diffs[0].tag_changed is True

    def test_env_diff_password_masked(self):
        result = self._call(load("replicasets.json"))
        assert "DB_PASSWORD" in result.env_diff
        prev_val, curr_val = result.env_diff["DB_PASSWORD"]
        assert prev_val == "[REDACTED]"
        assert curr_val == "[REDACTED]"

    def test_env_diff_log_level_changed(self):
        result = self._call(load("replicasets.json"))
        assert "LOG_LEVEL" in result.env_diff
        assert result.env_diff["LOG_LEVEL"] == ("INFO", "DEBUG")

    def test_resource_diff_detected(self):
        result = self._call(load("replicasets.json"))
        assert len(result.resource_diffs) > 0
        rd = result.resource_diffs[0]
        assert rd.from_cpu_request == "100m"
        assert rd.to_cpu_request == "200m"

    def test_replica_diff(self):
        result = self._call(load("replicasets.json"))
        assert result.replica_diff == (2, 3)

    def test_returns_none_when_deployment_not_found(self):
        from kubernetes.client.exceptions import ApiException

        mock_apps = MagicMock()
        mock_apps.read_namespaced_deployment.side_effect = ApiException(status=404)

        with patch("signalpilot.collectors.deploy._load_kube_config"), \
             patch("signalpilot.collectors.deploy.client") as mock_client:
            mock_client.AppsV1Api.return_value = mock_apps
            result = get_deploy_change("default", "nonexistent", settings=None)

        assert result is None

    def test_returns_none_with_single_replicaset(self):
        """Cannot compute a diff with only one revision."""
        data = {"items": [load("replicasets.json")["items"][0]]}
        result = self._call(data)
        assert result is None

    def test_namespace_set_correctly(self):
        result = self._call(load("replicasets.json"))
        assert result.namespace == "default"
        assert result.deployment == "api-server"
