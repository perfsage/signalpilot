"""
RCA engine for PerfSage SignalPilot.

Orchestrates:
1. Apply all RCA rules to collected evidence
2. Score and rank findings
3. Return Analysis with ranked findings
"""
from __future__ import annotations

import time
import uuid
from datetime import datetime, timezone
from typing import Optional

from signalpilot.models import (
    Analysis,
    DeployChange,
    LogCluster,
    RegressionWindow,
    Signal,
)
from signalpilot.rca.rules import ALL_RULES, RcaContext
from signalpilot.rca.scoring import rank_findings
from signalpilot.topology import TopologyBuilder


class RcaEngine:
    """
    Main RCA orchestrator.

    Usage:
        engine = RcaEngine()
        analysis = engine.analyze(
            namespace="my-ns",
            signals=signals,
            log_clusters=clusters,
            regressions=regressions,
            deploy_change=deploy,
            topology=topo_builder,
        )
    """

    def __init__(self) -> None:
        self._rules = list(ALL_RULES)

    def analyze(
        self,
        namespace: str,
        signals: list[Signal],
        log_clusters: Optional[list[LogCluster]] = None,
        regressions: Optional[list[RegressionWindow]] = None,
        deploy_change: Optional[DeployChange] = None,
        topology: Optional[TopologyBuilder] = None,
        deployment: Optional[str] = None,
        sources_used: Optional[list[str]] = None,
    ) -> Analysis:
        """Run all RCA rules and return a ranked Analysis."""
        start = time.monotonic()
        log_clusters = log_clusters or []
        regressions = regressions or []
        sources_used = sources_used or []

        ctx = RcaContext(
            signals=signals,
            log_clusters=log_clusters,
            regressions=regressions,
            deploy_change=deploy_change,
            namespace=namespace,
            deployment=deployment,
        )

        all_findings = []
        for rule_fn in self._rules:
            try:
                found = rule_fn(ctx)
                all_findings.extend(found)
            except Exception:
                pass  # rules must not break the engine

        ranked = rank_findings(all_findings, topo=topology)

        elapsed = time.monotonic() - start

        return Analysis(
            id=str(uuid.uuid4())[:12],
            ts=datetime.now(timezone.utc),
            namespace=namespace,
            deploy_change=deploy_change,
            regressions=regressions,
            log_clusters=log_clusters,
            topology=topology.graph() if topology else None,
            findings=ranked,
            narrative="",
            sources_used=sources_used,
            duration_s=elapsed,
        )
