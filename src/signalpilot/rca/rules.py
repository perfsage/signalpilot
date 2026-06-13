"""
RCA rule library for PerfSage SignalPilot.

Each rule is a function with signature:
    rule_fn(ctx: RcaContext) -> list[Finding]

Rules are pure functions — they receive all available evidence and return
zero or more Findings. The engine collects all findings from all rules,
then the scorer deduplicates and ranks them.
"""
from __future__ import annotations

import uuid
from typing import Optional

from signalpilot.models import (
    DeployChange,
    Finding,
    Fix,
    LogCluster,
    RegressionWindow,
    Severity,
    Signal,
    SignalKind,
    Target,
)


class RcaContext:
    """All available evidence passed to each RCA rule."""

    __slots__ = [
        "signals", "log_clusters", "regressions",
        "deploy_change", "namespace", "deployment",
    ]

    def __init__(
        self,
        signals: list[Signal],
        log_clusters: list[LogCluster],
        regressions: list[RegressionWindow],
        deploy_change: Optional[DeployChange],
        namespace: str,
        deployment: Optional[str] = None,
    ):
        self.signals = signals
        self.log_clusters = log_clusters
        self.regressions = regressions
        self.deploy_change = deploy_change
        self.namespace = namespace
        self.deployment = deployment

    def signals_by_kind(self, kind: SignalKind) -> list[Signal]:
        return [s for s in self.signals if s.kind == kind]

    def has_regression(self, metric: str) -> Optional[RegressionWindow]:
        for r in self.regressions:
            if r.metric == metric and r.is_regression:
                return r
        return None


def _finding_id() -> str:
    return str(uuid.uuid4())[:8]


# ─────────────────────────── Individual Rules ────────────────────────────── #

def rule_oom_killed(ctx: RcaContext) -> list[Finding]:
    """OOMKilled signal → undersized memory limit."""
    signals = ctx.signals_by_kind(SignalKind.OOM_KILLED)
    if not signals:
        return []

    findings = []
    for sig in signals:
        evidence: list = [sig]

        mem_sigs = [s for s in ctx.signals_by_kind(SignalKind.MEM_WORKING_SET)
                    if s.target.name == sig.target.name]
        evidence.extend(mem_sigs[:2])

        if ctx.deploy_change and ctx.deploy_change.git:
            gc = ctx.deploy_change.git
            if any("memory" in f.lower() or "mem" in f.lower()
                   for f in gc.suspect_files):
                evidence.append(gc)

        # Corroborate with log error rate signals
        log_err_sigs = [s for s in ctx.signals_by_kind(SignalKind.LOG_ERROR_RATE)
                        if s.target.name == sig.target.name]
        evidence.extend(log_err_sigs[:1])
        # Corroborate with event signals
        oom_event_sigs = [s for s in ctx.signals_by_kind(SignalKind.EVENT)
                          if any(kw in s.message for kw in ("OOM", "Killed", "memory"))]
        evidence.extend(oom_event_sigs[:1])

        current_limit = None
        proposed_limit = None
        if ctx.deploy_change and ctx.deploy_change.resource_diffs:
            for rd in ctx.deploy_change.resource_diffs:
                if rd.to_mem_limit:
                    current_limit = rd.to_mem_limit
                    try:
                        val = _parse_mem(current_limit)
                        proposed_limit = _format_mem(val * 2)
                    except Exception:
                        pass

        confidence = min(0.9 + 0.05 * len(mem_sigs), 1.0)

        findings.append(Finding(
            id=_finding_id(),
            title="Container OOMKilled — memory limit too low",
            severity=Severity.CRITICAL,
            confidence=confidence,
            blast_radius=0.0,
            target=sig.target,
            evidence=evidence,
            explanation=(
                f"Container {sig.target.container or sig.target.name} was killed by the OOM handler "
                f"(exit reason: OOMKilled). The container is hitting its memory limit. "
                + (f"Memory working set: {mem_sigs[0].value / (1024 ** 2):.0f}MB. " if mem_sigs else "")
                + "Raise the memory limit and investigate for memory leaks."
            ),
            fixes=[Fix(
                description="Raise container memory limit",
                kind="patch",
                kubectl_snippet=(
                    f'kubectl set resources deployment {sig.target.name.split("-")[0]} '
                    f'-c {sig.target.container or "app"} '
                    + (f"--limits=memory={proposed_limit}" if proposed_limit else "--limits=memory=<NEW_LIMIT>")
                ),
                expected_improvement="OOMKilled events should stop",
                current_value=current_limit,
                proposed_value=proposed_limit,
            )],
            rule_id="oom_killed",
        ))
    return findings


def rule_cpu_throttled(ctx: RcaContext) -> list[Finding]:
    """High CPU throttling → raise CPU limit/request."""
    throttle_sigs = ctx.signals_by_kind(SignalKind.CPU_THROTTLED)
    high_throttle = [s for s in throttle_sigs if s.value and s.value > 0.3]

    if not high_throttle:
        cpu_sigs = [s for s in ctx.signals_by_kind(SignalKind.CPU_USAGE)
                    if s.severity in (Severity.HIGH, Severity.CRITICAL)]
        if not cpu_sigs:
            return []
        high_throttle = cpu_sigs

    latency_reg = ctx.has_regression(SignalKind.LATENCY_P95.value)

    evidence = list(high_throttle[:3])
    sig = high_throttle[0]

    confidence = 0.7
    if latency_reg:
        confidence = min(confidence + 0.2, 1.0)

    current_limit = None
    proposed_limit = None
    if ctx.deploy_change and ctx.deploy_change.resource_diffs:
        for rd in ctx.deploy_change.resource_diffs:
            if rd.to_cpu_limit:
                current_limit = rd.to_cpu_limit
                try:
                    millis = _parse_cpu(current_limit)
                    proposed_limit = f"{int(millis * 2)}m"
                except Exception:
                    pass

    return [Finding(
        id=_finding_id(),
        title="CPU throttling detected — container hitting CPU limit",
        severity=Severity.HIGH,
        confidence=confidence,
        blast_radius=0.0,
        target=sig.target,
        evidence=evidence,
        explanation=(
            f"Container {sig.target.container or sig.target.name} CPU is being throttled by the kernel "
            f"CFS scheduler. Value: {sig.value:.0%} throttle rate. "
            + ("Corroborated by latency regression. " if latency_reg else "")
            + "Raise the CPU request and limit to reduce throttling."
        ),
        fixes=[Fix(
            description="Raise CPU limit to reduce throttling",
            kind="patch",
            kubectl_snippet=(
                "kubectl set resources deployment "
                + (ctx.deployment or sig.target.name.rsplit("-", 2)[0])
                + f" --limits=cpu={proposed_limit or '<NEW_LIMIT>'}"
                + (f" --requests=cpu={proposed_limit}" if proposed_limit else "")
            ),
            expected_improvement="CPU throttling should drop below 5%",
            current_value=current_limit,
            proposed_value=proposed_limit,
        )],
        rule_id="cpu_throttled",
    )]


def rule_crash_loop(ctx: RcaContext) -> list[Finding]:
    """CrashLoopBackOff → bad config, missing dependency, or code error."""
    crash_sigs = ctx.signals_by_kind(SignalKind.CRASH_LOOP)
    if not crash_sigs:
        return []

    sig = crash_sigs[0]
    evidence: list = list(crash_sigs[:2])

    conn_clusters = [c for c in ctx.log_clusters
                     if c.is_new and c.category in ("conn", "timeout", None)]
    evidence.extend(conn_clusters[:2])
    # Corroborate with log error rate signals
    log_err_sigs = [s for s in ctx.signals_by_kind(SignalKind.LOG_ERROR_RATE)
                    if s.value and s.value > 0]
    evidence.extend(log_err_sigs[:1])

    config_changed = bool(ctx.deploy_change and (
        ctx.deploy_change.env_diff or ctx.deploy_change.config_ref_changes
    ))

    if ctx.deploy_change and ctx.deploy_change.git and ctx.deploy_change.git.suspect_commits:
        evidence.append(ctx.deploy_change.git)

    explanation = (
        f"Container {sig.target.container or sig.target.name} is in CrashLoopBackOff, "
        f"indicating repeated crash-restart cycles. "
    )
    if config_changed:
        explanation += "A config/env change was deployed — verify env vars and ConfigMap keys are correct. "
    if conn_clusters:
        explanation += "Logs show connection-related errors — check dependency availability. "
    explanation += "Check container logs for the root cause (exit code, stacktrace)."

    fixes = [Fix(
        description="Check container logs for crash reason",
        kind="info",
        kubectl_snippet=f"kubectl logs {sig.target.name} -c {sig.target.container or 'app'} --previous",
        expected_improvement="Identify crash cause from logs",
    )]
    if config_changed:
        fixes.append(Fix(
            description="Roll back to previous revision if config change is the cause",
            kind="rollback",
            kubectl_snippet=f"kubectl rollout undo deployment/{ctx.deployment or sig.target.name.rsplit('-', 2)[0]}",
            expected_improvement="CrashLoopBackOff should stop if config change was the cause",
        ))

    confidence = 0.85
    if conn_clusters:
        confidence = min(confidence + 0.1, 1.0)

    return [Finding(
        id=_finding_id(),
        title="CrashLoopBackOff — container repeatedly crashing",
        severity=Severity.CRITICAL,
        confidence=confidence,
        blast_radius=0.0,
        target=sig.target,
        evidence=evidence,
        explanation=explanation,
        fixes=fixes,
        rule_id="crash_loop",
    )]


def rule_image_pull_error(ctx: RcaContext) -> list[Finding]:
    """ImagePullBackOff/ErrImagePull → bad image tag or registry issue."""
    img_sigs = ctx.signals_by_kind(SignalKind.IMAGE_PULL_ERROR)
    if not img_sigs:
        return []

    sig = img_sigs[0]
    evidence: list = list(img_sigs[:2])
    # Corroborate with events
    event_sigs = [s for s in ctx.signals_by_kind(SignalKind.EVENT)
                  if any(kw in s.message for kw in ("ImagePull", "ErrImage", "pull", "image"))]
    evidence.extend(event_sigs[:2])
    # Corroborate with PENDING or PROBE signals
    other_sigs = ctx.signals_by_kind(SignalKind.PENDING_POD) + ctx.signals_by_kind(SignalKind.PROBE_FAILURE)
    evidence.extend(other_sigs[:1])

    bad_image = None
    if ctx.deploy_change and ctx.deploy_change.image_diffs:
        bad_image = ctx.deploy_change.image_diffs[0].to_image

    return [Finding(
        id=_finding_id(),
        title="ImagePullBackOff — container image cannot be pulled",
        severity=Severity.CRITICAL,
        confidence=0.98,
        blast_radius=0.0,
        target=sig.target,
        evidence=evidence,
        explanation=(
            "Kubernetes cannot pull the container image"
            + (f" '{bad_image}'" if bad_image else "")
            + ". Possible causes: wrong tag, registry auth failure, network issue, or image doesn't exist."
        ),
        fixes=[
            Fix(
                description="Verify the image tag exists in the registry",
                kind="info",
                kubectl_snippet=(
                    f"kubectl describe pod -n {ctx.namespace} "
                    f"-l app={ctx.deployment or sig.target.name.rsplit('-', 2)[0]}"
                ),
                expected_improvement="Confirm exact error (auth vs tag not found)",
            ),
            Fix(
                description="Roll back to previous image",
                kind="rollback",
                kubectl_snippet=f"kubectl rollout undo deployment/{ctx.deployment or sig.target.name.rsplit('-', 2)[0]}",
                expected_improvement="Pods should start pulling the previous working image",
            ),
        ],
        rule_id="image_pull_error",
    )]


def rule_probe_failure(ctx: RcaContext) -> list[Finding]:
    """Readiness/liveness probe failures → probe misconfiguration."""
    probe_sigs = ctx.signals_by_kind(SignalKind.PROBE_FAILURE)
    if not probe_sigs:
        return []

    sig = probe_sigs[0]
    evidence: list = list(probe_sigs[:2])
    event_sigs = [s for s in ctx.signals_by_kind(SignalKind.EVENT)
                  if any(kw in s.message for kw in ("Unhealthy", "probe", "Readiness", "Liveness"))]
    evidence.extend(event_sigs[:1])
    # Add log signals as corroborating evidence
    log_err_sigs = ctx.signals_by_kind(SignalKind.LOG_ERROR_RATE)
    evidence.extend(log_err_sigs[:1])

    probe_info = ""
    if ctx.deploy_change and ctx.deploy_change.image_diffs:
        probe_info = "A new image was deployed — verify probe paths/ports match the new version. "

    return [Finding(
        id=_finding_id(),
        title="Readiness/liveness probe failing — service endpoints not ready",
        severity=Severity.HIGH,
        confidence=0.80,
        blast_radius=0.0,
        target=sig.target,
        evidence=evidence,
        explanation=(
            f"Pod {sig.target.name} probe is failing, causing it to be removed from Service endpoints. "
            + probe_info
            + "Check probe path, port, timing parameters, and whether the application is actually healthy."
        ),
        fixes=[
            Fix(
                description="Inspect probe configuration",
                kind="info",
                kubectl_snippet=f"kubectl describe pod {sig.target.name} -n {ctx.namespace}",
                expected_improvement="Identify exact probe type and failure reason",
            ),
            Fix(
                description="Increase probe initialDelaySeconds if app needs more startup time",
                kind="patch",
                yaml_snippet=(
                    "livenessProbe:\n  initialDelaySeconds: 60  # increase from current value\n"
                    "  periodSeconds: 10\n  failureThreshold: 3"
                ),
                expected_improvement="Probes should pass after application finishes starting",
            ),
        ],
        rule_id="probe_failure",
    )]


def rule_pending_unschedulable(ctx: RcaContext) -> list[Finding]:
    """Pending pods → insufficient node capacity."""
    pending_sigs = ctx.signals_by_kind(SignalKind.PENDING_POD)
    if not pending_sigs:
        return []

    event_sigs = [s for s in ctx.signals_by_kind(SignalKind.EVENT)
                  if "FailedScheduling" in s.message or "Insufficient" in s.message]

    sig = pending_sigs[0]
    evidence: list = list(pending_sigs[:2]) + list(event_sigs[:2])
    # Corroborate with node condition signals (resource requests)
    node_cond_sigs = ctx.signals_by_kind(SignalKind.NODE_CONDITION)
    evidence.extend(node_cond_sigs[:1])
    # Corroborate with probe failure signals
    probe_sigs_corr = ctx.signals_by_kind(SignalKind.PROBE_FAILURE)
    evidence.extend(probe_sigs_corr[:1])

    return [Finding(
        id=_finding_id(),
        title="Pod unschedulable — insufficient cluster capacity",
        severity=Severity.HIGH,
        confidence=0.90 if event_sigs else 0.80,
        blast_radius=0.0,
        target=sig.target,
        evidence=evidence,
        explanation=(
            f"Pod {sig.target.name} is stuck in Pending state. "
            + (f"Events indicate: {event_sigs[0].message} " if event_sigs else "")
            + "The cluster may not have sufficient CPU/memory to schedule this pod."
        ),
        fixes=[
            Fix(
                description="Check node capacity and pod resource requests",
                kind="info",
                kubectl_snippet="kubectl describe nodes | grep -A5 'Allocated resources'",
                expected_improvement="Identify which resource is exhausted",
            ),
            Fix(
                description="Reduce CPU/memory requests if over-requested",
                kind="patch",
                kubectl_snippet=f"kubectl set resources deployment/{ctx.deployment or 'DEPLOYMENT'} --requests=cpu=100m,memory=128Mi",
                expected_improvement="Pod should schedule if requests are within node capacity",
            ),
        ],
        rule_id="pending_unschedulable",
    )]


def rule_code_regression(ctx: RcaContext) -> list[Finding]:
    """New error log pattern after deploy → code regression."""
    new_error_clusters = [c for c in ctx.log_clusters if c.is_new]
    if not new_error_clusters:
        return []

    err_reg = ctx.has_regression(SignalKind.LOG_ERROR_RATE.value)

    evidence: list = list(new_error_clusters[:3])
    if ctx.deploy_change and ctx.deploy_change.git:
        evidence.append(ctx.deploy_change.git)
    # Corroborate with log error rate signals
    log_err_sigs = [s for s in ctx.signals_by_kind(SignalKind.LOG_ERROR_RATE)
                    if s.value and s.value > 0]
    evidence.extend(log_err_sigs[:1])

    suspect_info = ""
    if ctx.deploy_change and ctx.deploy_change.git:
        gc = ctx.deploy_change.git
        if gc.suspect_commits:
            suspect_info = (
                f" Suspect commit: {gc.suspect_commits[0].sha[:8]} "
                f"by {gc.suspect_commits[0].author}: '{gc.suspect_commits[0].message[:80]}'."
            )

    confidence = 0.75
    if err_reg:
        confidence = min(confidence + 0.15, 1.0)
    if ctx.deploy_change and ctx.deploy_change.git and ctx.deploy_change.git.suspect_commits:
        confidence = min(confidence + 0.10, 1.0)

    target = Target(
        kind="Deployment",
        namespace=ctx.namespace,
        name=ctx.deployment or ctx.namespace,
    )

    return [Finding(
        id=_finding_id(),
        title=f"Code regression after deploy — {len(new_error_clusters)} new error pattern(s)",
        severity=Severity.HIGH,
        confidence=confidence,
        blast_radius=0.0,
        target=target,
        evidence=evidence,
        explanation=(
            f"{len(new_error_clusters)} new error log pattern(s) appeared after deployment. "
            f"Most common: '{new_error_clusters[0].template[:100]}' ({new_error_clusters[0].count_after}x)."
            + suspect_info
        ),
        fixes=[
            Fix(
                description="Roll back the deployment to previous revision",
                kind="rollback",
                kubectl_snippet=f"kubectl rollout undo deployment/{ctx.deployment or 'DEPLOYMENT'}",
                expected_improvement="New error patterns should disappear",
            ),
        ],
        rule_id="code_regression",
    )]


def rule_latency_spike(ctx: RcaContext) -> list[Finding]:
    """WARN/slow latency patterns in logs → p95 regression."""
    latency_clusters = [
        c for c in ctx.log_clusters
        if c.is_new and any(
            kw in c.template.lower()
            for kw in ("slow", "latency", "p95", "p99", "warn", "timeout", "deadline")
        )
    ]
    latency_reg = ctx.has_regression(SignalKind.LATENCY_P95.value)
    prom_sigs = ctx.signals_by_kind(SignalKind.LATENCY_P95)

    if not latency_clusters and not prom_sigs and not latency_reg:
        return []

    evidence: list = list(latency_clusters[:3]) + list(prom_sigs[:2])
    # Corroborate with log error rate signals that show slow request patterns
    log_sigs = [s for s in ctx.signals_by_kind(SignalKind.LOG_ERROR_RATE)
                if s.value and s.value > 0]
    evidence.extend(log_sigs[:1])

    primary_cluster = latency_clusters[0] if latency_clusters else None
    primary_sig = prom_sigs[0] if prom_sigs else None

    if not evidence:
        return []

    target = Target(
        kind="Deployment",
        namespace=ctx.namespace,
        name=ctx.deployment or ctx.namespace,
    )

    confidence = 0.75
    if latency_clusters:
        confidence = min(confidence + 0.05 * len(latency_clusters), 0.95)

    sample = (
        primary_cluster.template[:80] if primary_cluster
        else (primary_sig.message[:80] if primary_sig else "latency spike detected")
    )

    return [Finding(
        id=_finding_id(),
        title="Latency spike — p95 regression detected in logs",
        severity=Severity.HIGH,
        confidence=confidence,
        blast_radius=0.0,
        target=target,
        evidence=evidence,
        explanation=(
            f"Log patterns indicate p95 latency regression: '{sample}'. "
            + (f"{len(latency_clusters)} new slow-request pattern(s) appeared. " if latency_clusters else "")
            + "Profile the application to find the slow code path."
        ),
        fixes=[
            Fix(
                description="Check slow request patterns in logs",
                kind="info",
                kubectl_snippet=(
                    f"kubectl logs -n {ctx.namespace} "
                    f"-l app={ctx.deployment or 'DEPLOYMENT'} | grep -i 'slow\\|warn\\|latency'"
                ),
                expected_improvement="Identify which requests are slow and why",
            ),
        ],
        rule_id="latency_spike",
    )]


def rule_configmap_error(ctx: RcaContext) -> list[Finding]:
    """CreateContainerConfigError → missing or invalid ConfigMap/Secret mount."""
    config_event_sigs = [
        s for s in ctx.signals_by_kind(SignalKind.EVENT)
        if any(kw in s.message for kw in (
            "CreateContainerConfigError", "ConfigError",
            "configmap", "secret", "MountVolume", "couldn't find key",
        ))
    ]
    crash_sigs = ctx.signals_by_kind(SignalKind.CRASH_LOOP)

    if not config_event_sigs:
        return []

    sig = config_event_sigs[0]
    evidence: list = list(config_event_sigs[:3])
    evidence.extend(crash_sigs[:1])
    # Corroborate with PENDING_POD signals
    pending_corr = ctx.signals_by_kind(SignalKind.PENDING_POD)
    evidence.extend(pending_corr[:1])

    return [Finding(
        id=_finding_id(),
        title="Missing ConfigMap or Secret — container stuck in CreateContainerConfigError",
        severity=Severity.CRITICAL,
        confidence=0.95,
        blast_radius=0.0,
        target=sig.target,
        evidence=evidence,
        explanation=(
            "Kubernetes cannot start the container because a referenced ConfigMap or Secret "
            "does not exist or is missing a required key. "
            f"Event: '{sig.message[:120]}'. "
            "Create the missing ConfigMap/Secret or fix the volume/env reference."
        ),
        fixes=[
            Fix(
                description="Check which ConfigMap/Secret is missing",
                kind="info",
                kubectl_snippet=(
                    f"kubectl describe pod -n {ctx.namespace} "
                    f"-l app={ctx.deployment or 'DEPLOYMENT'}"
                ),
                expected_improvement="Identify the exact missing resource",
            ),
            Fix(
                description="Create the missing ConfigMap",
                kind="config",
                kubectl_snippet=(
                    f"kubectl create configmap <NAME> --from-literal=key=value "
                    f"-n {ctx.namespace}"
                ),
                expected_improvement="Pod should move past CreateContainerConfigError",
            ),
        ],
        rule_id="configmap_error",
    )]


def rule_init_container_fail(ctx: RcaContext) -> list[Finding]:
    """Init container failure → pod stuck in Init:Error or Init:CrashLoopBackOff."""
    # Detect via kube_api CRASH_LOOP signals with the [init:fail] marker
    crash_sigs = [
        s for s in ctx.signals_by_kind(SignalKind.CRASH_LOOP)
        if "[init:fail]" in s.message or "init" in s.message.lower()
    ]
    # Detect via K8s events (BackOff on init container)
    init_event_sigs = [
        s for s in ctx.signals_by_kind(SignalKind.EVENT)
        if any(kw.lower() in s.message.lower()
               for kw in ("back-off", "backoff", "Init:", "init container"))
    ]
    kube_sigs = [
        s for s in ctx.signals_by_kind(SignalKind.RESTART)
        if "init" in s.message.lower()
    ]

    all_init_sigs = crash_sigs + init_event_sigs + kube_sigs
    if not all_init_sigs:
        return []

    sig = all_init_sigs[0]
    evidence: list = list(all_init_sigs[:3])

    # Corroborate with PENDING_POD signals
    pending_sigs_corr = ctx.signals_by_kind(SignalKind.PENDING_POD)
    evidence.extend(pending_sigs_corr[:1])

    error_clusters = [c for c in ctx.log_clusters if c.is_new]
    evidence.extend(error_clusters[:2])

    return [Finding(
        id=_finding_id(),
        title="Init container failed — pod cannot start",
        severity=Severity.CRITICAL,
        confidence=0.90,
        blast_radius=0.0,
        target=sig.target,
        evidence=evidence,
        explanation=(
            "An init container exited with a non-zero code, preventing the main container "
            "from ever starting. "
            + (f"Error: '{sig.message[:120]}'. " if sig.message else "")
            + "Fix the init container command, image, or its dependencies."
        ),
        fixes=[
            Fix(
                description="Check init container logs for failure reason",
                kind="info",
                kubectl_snippet=(
                    f"kubectl logs -n {ctx.namespace} "
                    f"-l app={ctx.deployment or 'DEPLOYMENT'} "
                    "-c init-checker --previous"
                ),
                expected_improvement="Identify exit code and error message",
            ),
            Fix(
                description="Describe pod to see init container status",
                kind="info",
                kubectl_snippet=(
                    f"kubectl describe pod -n {ctx.namespace} "
                    f"-l app={ctx.deployment or 'DEPLOYMENT'}"
                ),
                expected_improvement="See init container exit code and events",
            ),
        ],
        rule_id="init_container_fail",
    )]


def rule_network_latency(ctx: RcaContext) -> list[Finding]:
    """TCP retransmits or DNS failures → network/dependency latency."""
    tcp_sigs = ctx.signals_by_kind(SignalKind.TCP_RETRANSMIT)
    dns_sigs = ctx.signals_by_kind(SignalKind.DNS_LATENCY)

    if not tcp_sigs and not dns_sigs:
        return []

    evidence: list = list(tcp_sigs[:2]) + list(dns_sigs[:2])
    primary = (tcp_sigs or dns_sigs)[0]

    is_dns = bool(dns_sigs) and not tcp_sigs
    title = "DNS latency/failures detected" if is_dns else "TCP retransmits detected — network latency"
    explanation = (
        ("DNS resolution failures or high latency detected. Check CoreDNS pods and DNS upstream. "
         if is_dns else
         f"TCP retransmits detected ({tcp_sigs[0].value:.0f} occurrences). "
         "This indicates packet loss or network congestion, not application-level slowness. ")
        + "Investigate network policies, service mesh, and upstream dependency health."
    )

    return [Finding(
        id=_finding_id(),
        title=title,
        severity=Severity.HIGH if tcp_sigs and tcp_sigs[0].severity == Severity.HIGH else Severity.MEDIUM,
        confidence=0.70,
        blast_radius=0.0,
        target=primary.target,
        evidence=evidence,
        explanation=explanation,
        fixes=[
            Fix(
                description="Check CoreDNS health" if is_dns else "Run deep network capture to quantify packet loss",
                kind="info",
                kubectl_snippet=(
                    "kubectl get pods -n kube-system -l k8s-app=kube-dns" if is_dns
                    else "signalpilot analyze --deep-network --namespace " + ctx.namespace
                ),
                expected_improvement="Identify DNS/network root cause",
            ),
        ],
        rule_id="network_latency",
    )]


# ── Helpers ─────────────────────────────────────────────────────────────── #

def _parse_mem(value: str) -> int:
    """Parse '128Mi' → bytes."""
    value = value.strip()
    units = {"Ki": 1024, "Mi": 1024 ** 2, "Gi": 1024 ** 3, "Ti": 1024 ** 4, "": 1}
    for suffix, mult in sorted(units.items(), key=lambda x: -len(x[0])):
        if value.endswith(suffix):
            return int(value[: -len(suffix) or None]) * mult
    return int(value)


def _format_mem(bytes_val: int) -> str:
    """Format bytes as Kubernetes memory string."""
    if bytes_val >= 1024 ** 3:
        return f"{bytes_val // 1024 ** 3}Gi"
    if bytes_val >= 1024 ** 2:
        return f"{bytes_val // 1024 ** 2}Mi"
    return f"{bytes_val}Ki"


def _parse_cpu(value: str) -> float:
    """Parse '500m' → 500.0 millicores; '2' → 2000.0 millicores."""
    value = value.strip()
    if value.endswith("m"):
        return float(value[:-1])
    return float(value) * 1000


# ── Rule registry ────────────────────────────────────────────────────────── #

ALL_RULES = [
    rule_oom_killed,
    rule_cpu_throttled,
    rule_crash_loop,
    rule_image_pull_error,
    rule_probe_failure,
    rule_pending_unschedulable,
    rule_code_regression,
    rule_network_latency,
    rule_configmap_error,
    rule_init_container_fail,
    rule_latency_spike,
]
