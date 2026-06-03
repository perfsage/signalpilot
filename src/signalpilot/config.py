"""Settings, thresholds, and environment variable configuration for SignalPilot.

All settings are overridable via environment variables prefixed with
``SIGNALPILOT_`` or via a ``.env`` file in the working directory.
"""

from __future__ import annotations

from typing import Optional

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration for SignalPilot.

    Environment variables are mapped by uppercasing the field name and
    prepending ``SIGNALPILOT_``.  Example: ``SIGNALPILOT_PROMETHEUS_URL``.
    """

    model_config = SettingsConfigDict(
        env_prefix="SIGNALPILOT_",
        env_file=".env",
        extra="ignore",
    )

    # Kubernetes
    kubeconfig: Optional[str] = None
    kube_context: Optional[str] = None

    # Analysis window (seconds before/after deploy used as baseline / analysis)
    baseline_window_s: int = 1800
    analysis_window_s: int = 900

    # Regression detection thresholds
    regression_z_score_threshold: float = 2.0
    regression_min_pct_change: float = 0.20

    # Log analysis
    log_tail_lines: int = 5000
    log_max_clusters: int = 200

    # Prometheus
    prometheus_url: Optional[str] = None
    prometheus_timeout_s: float = 10.0

    # Loki
    loki_url: Optional[str] = None

    # OTel / Jaeger
    jaeger_url: Optional[str] = None

    # LLM (optional narrative generation)
    llm_provider: Optional[str] = None
    llm_model: Optional[str] = None
    llm_api_key: Optional[str] = Field(default=None, exclude=True)
    llm_max_tokens: int = 1000

    # Slack notifications
    slack_webhook_url: Optional[str] = Field(default=None, exclude=True)

    # CI gate
    gate_severity_threshold: str = "high"

    # Local storage directory for Parquet snapshots
    data_dir: str = ".signalpilot"

    # Network deep-dive
    deep_network_timeout_s: int = 30
    tcpdump_capture_s: int = 15


def get_settings() -> Settings:
    """Return a fully resolved Settings instance (reads env + .env file)."""
    return Settings()
