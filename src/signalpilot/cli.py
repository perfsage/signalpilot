"""
PerfSage SignalPilot CLI.

Commands:
  analyze  — Run full RCA analysis on a namespace/deployment
  watch    — Watch for deploys and auto-analyze (continuous)
  gate     — CI/CD gate: exit non-zero if findings above threshold
  serve    — Launch web dashboard
  verify   — Compare current state against a saved baseline
"""
from __future__ import annotations

import time
from datetime import datetime
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from signalpilot.config import get_settings
from signalpilot.models import Analysis, Severity

app = typer.Typer(
    name="signalpilot",
    help="PerfSage SignalPilot — Kubernetes RCA copilot",
    no_args_is_help=True,
)
console = Console()


def _run_analysis(
    namespace: str,
    deployment: Optional[str],
    git_repo: Optional[str],
    deep_network: bool,
    output: Optional[Path],
    quiet: bool,
) -> Analysis:
    """Core analysis pipeline. Returns Analysis object."""
    from signalpilot.analysis.logs import cluster_logs
    from signalpilot.collectors.deploy import get_deploy_change
    from signalpilot.collectors.logs import LogsCollector
    from signalpilot.collectors.registry import CollectorRegistry
    from signalpilot.detect.regression import detect_regressions
    from signalpilot.narrate.llm import polish_narrative
    from signalpilot.rca.engine import RcaEngine
    from signalpilot.report.html import generate_html_report
    from signalpilot.topology import TopologyBuilder

    settings = get_settings()

    if not quiet:
        console.print(
            f"[bold blue]⚡ SignalPilot[/bold blue] analyzing namespace "
            f"[yellow]{namespace}[/yellow]..."
        )

    # 1. Load kube config
    try:
        from kubernetes import config as kube_config

        if settings.kubeconfig:
            kube_config.load_kube_config(
                config_file=settings.kubeconfig, context=settings.kube_context
            )
        else:
            try:
                kube_config.load_incluster_config()
            except Exception:
                kube_config.load_kube_config(context=settings.kube_context)
    except Exception as e:
        console.print(f"[red]Error loading kubeconfig: {e}[/red]")
        raise typer.Exit(1)

    # 2. Collect signals
    registry = CollectorRegistry(settings)
    registry.register_defaults()
    signals = registry.collect_all(namespace, deployment)

    # 3. Collect logs for clustering (previous = before, current = after)
    log_collector = LogsCollector(settings)
    _raw_logs: dict[str, str] = {}
    try:
        _raw_logs = log_collector.collect_raw(namespace, deployment)
    except Exception:
        pass
    before_logs = _raw_logs.get("previous", "")
    after_logs = _raw_logs.get("current", "")
    log_clusters = (
        cluster_logs(before_logs, after_logs)
        if (before_logs or after_logs)
        else []
    )

    # 4. Get deploy change
    deploy_change = None
    if deployment:
        try:
            deploy_change = get_deploy_change(namespace, deployment, settings)
            if deploy_change and git_repo:
                from signalpilot.collectors.git import enrich_deploy_change

                deploy_change = enrich_deploy_change(deploy_change, git_repo)
        except Exception:
            pass

    # 5. Build topology
    topo = TopologyBuilder(settings)
    try:
        topo.build(namespace)
    except Exception:
        pass

    # 6. Detect regressions (split signals before/after deploy)
    from signalpilot.timeline import SignalTimeline

    timeline = SignalTimeline()
    timeline.add(signals)
    if deploy_change:
        before_sigs, after_sigs = timeline.window(
            deploy_change.deploy_time,
            baseline_s=settings.baseline_window_s,
            analysis_s=settings.analysis_window_s,
        )
        regressions = detect_regressions(before_sigs, after_sigs, target_name=deployment)
    else:
        regressions = []

    # 7. Run RCA
    sources_used = registry.available_collector_names()
    engine = RcaEngine()
    analysis = engine.analyze(
        namespace=namespace,
        signals=signals,
        log_clusters=log_clusters,
        regressions=regressions,
        deploy_change=deploy_change,
        topology=topo,
        deployment=deployment,
        sources_used=sources_used,
    )

    # 8. Generate narrative
    analysis = analysis.model_copy(update={"narrative": polish_narrative(analysis)})

    # 9. Output
    if output:
        path = generate_html_report(analysis, output_path=output)
        if not quiet:
            console.print(f"[green]Report written to {path}[/green]")

    return analysis


@app.command()
def analyze(
    namespace: str = typer.Argument(..., help="Kubernetes namespace to analyze"),
    deployment: Optional[str] = typer.Option(
        None, "--deployment", "-d", help="Specific deployment name"
    ),
    git_repo: Optional[str] = typer.Option(
        None, "--git-repo", "-g", help="App git repo URL or local path for code correlation"
    ),
    output: Optional[Path] = typer.Option(
        None, "--output", "-o", help="Write HTML report to this path"
    ),
    json_out: Optional[Path] = typer.Option(
        None, "--json-out", help="Write JSON analysis dump to this path"
    ),
    deep_network: bool = typer.Option(
        False, "--deep-network", help="Enable packet-level network analysis"
    ),
    quiet: bool = typer.Option(False, "--quiet", "-q", help="Minimal output"),
    gate: bool = typer.Option(False, "--gate", help="Exit non-zero if findings above threshold"),
    slack: bool = typer.Option(False, "--slack", help="Send Slack alert if webhook configured"),
) -> None:
    """Run full RCA analysis on a namespace."""
    settings = get_settings()

    analysis = _run_analysis(namespace, deployment, git_repo, deep_network, output, quiet)

    if json_out:
        json_out.write_text(analysis.model_dump_json(indent=2))

    if not quiet:
        _print_analysis(analysis)

    if slack and settings.slack_webhook_url:
        from signalpilot.integrations.slack import send_slack_alert

        send_slack_alert(analysis, settings.slack_webhook_url)

    if gate:
        from signalpilot.integrations.gate import gate_check

        threshold = settings.gate_severity_threshold
        if not gate_check(analysis, threshold):
            console.print(
                f"[red]Gate FAILED: findings at or above {threshold.value}[/red]"
            )
            raise typer.Exit(1)


@app.command()
def gate(
    namespace: str = typer.Argument(..., help="Namespace to check"),
    deployment: Optional[str] = typer.Option(None, "--deployment", "-d"),
    threshold: str = typer.Option(
        "high",
        "--threshold",
        "-t",
        help="Severity threshold: critical/high/medium/low",
    ),
    junit_xml: Optional[Path] = typer.Option(
        None, "--junit-xml", help="Write JUnit XML to this path"
    ),
    markdown: Optional[Path] = typer.Option(
        None, "--markdown", help="Write Markdown summary to this path"
    ),
) -> None:
    """CI/CD gate: exit 1 if findings at or above threshold severity."""
    try:
        sev_threshold = Severity(threshold)
    except ValueError:
        console.print(
            f"[red]Invalid threshold '{threshold}'. Use: critical/high/medium/low/info[/red]"
        )
        raise typer.Exit(2)

    analysis = _run_analysis(namespace, deployment, None, False, None, True)

    from signalpilot.integrations.gate import (
        gate_check,
        generate_junit_xml,
        generate_markdown_summary,
    )

    if junit_xml:
        generate_junit_xml(analysis, junit_xml)
    if markdown:
        markdown.write_text(generate_markdown_summary(analysis))

    passed = gate_check(analysis, sev_threshold)

    md_summary = generate_markdown_summary(analysis)
    console.print(md_summary)

    if not passed:
        console.print(
            f"[red bold]❌ Gate FAILED[/red bold]: {len(analysis.findings)} "
            f"finding(s) at or above [{threshold.upper()}]"
        )
        raise typer.Exit(1)
    else:
        console.print("[green bold]✅ Gate PASSED[/green bold]")


@app.command()
def serve(
    host: str = typer.Option("127.0.0.1", "--host"),
    port: int = typer.Option(8080, "--port"),
) -> None:
    """Launch the web dashboard."""
    import uvicorn

    from signalpilot.web.app import create_app

    web_app = create_app()
    uvicorn.run(web_app, host=host, port=port)


@app.command()
def watch(
    namespace: str = typer.Argument(...),
    deployment: Optional[str] = typer.Option(None, "--deployment", "-d"),
    interval: int = typer.Option(60, "--interval", help="Poll interval in seconds"),
    output_dir: Optional[Path] = typer.Option(None, "--output-dir"),
) -> None:
    """Watch for changes and auto-analyze on new deploys."""
    console.print(f"[blue]Watching {namespace} every {interval}s...[/blue]")
    last_revision = None
    while True:
        try:
            analysis = _run_analysis(namespace, deployment, None, False, None, True)
            rev = analysis.deploy_change.to_revision if analysis.deploy_change else None
            if rev != last_revision:
                last_revision = rev
                console.print(f"\n[bold]New deploy detected[/bold] (revision {rev})")
                _print_analysis(analysis)
                if output_dir:
                    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
                    out = output_dir / f"report_{ts}.html"
                    from signalpilot.report.html import generate_html_report

                    generate_html_report(analysis, output_path=out)
        except Exception as e:
            console.print(f"[yellow]Watch error: {e}[/yellow]")
        time.sleep(interval)


@app.command()
def verify(
    namespace: str = typer.Argument(...),
    deployment: Optional[str] = typer.Option(None, "--deployment", "-d"),
    baseline_id: Optional[str] = typer.Option(
        None, "--baseline-id", help="Baseline analysis ID to compare against"
    ),
) -> None:
    """Verify current state against a saved baseline."""
    from signalpilot.verification.store import VerificationStore

    store = VerificationStore()

    analysis = _run_analysis(namespace, deployment, None, False, None, False)

    if baseline_id:
        baseline = store.load(baseline_id)
        if baseline:
            comparison = store.compare(baseline, analysis)
            console.print(Panel(comparison, title="Verification Result"))
        else:
            console.print(
                f"[yellow]Baseline '{baseline_id}' not found. "
                f"Saving current as baseline.[/yellow]"
            )
            store.save(analysis)
    else:
        store.save(analysis)
        console.print(f"[green]Baseline saved: {analysis.id}[/green]")

    _print_analysis(analysis)


def _print_analysis(analysis: Analysis) -> None:
    """Pretty-print analysis to console."""
    if not analysis.findings:
        console.print(
            Panel("[green]✅ No significant issues detected.[/green]", title="SignalPilot Result")
        )
        return

    table = Table(
        title=f"SignalPilot Findings — {analysis.namespace}",
        show_header=True,
        header_style="bold cyan",
    )
    table.add_column("Sev", style="bold", min_width=8)
    table.add_column("Title", min_width=40)
    table.add_column("Target", min_width=20)
    table.add_column("Conf", justify="right")
    table.add_column("Top Fix", min_width=40)

    _SEV_COLOR = {
        Severity.CRITICAL: "red",
        Severity.HIGH: "orange1",
        Severity.MEDIUM: "yellow",
        Severity.LOW: "green",
        Severity.INFO: "blue",
    }

    for finding in analysis.findings:
        color = _SEV_COLOR.get(finding.severity, "white")
        fix_text = finding.fixes[0].description[:40] if finding.fixes else ""
        table.add_row(
            Text(finding.severity.value.upper(), style=color),
            finding.title[:55],
            f"{finding.target.kind}/{finding.target.name}",
            f"{finding.confidence:.0%}",
            fix_text,
        )

    console.print(table)

    if analysis.narrative:
        console.print(Panel(analysis.narrative[:500], title="Summary"))
