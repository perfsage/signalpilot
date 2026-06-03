"""Command-line interface for SignalPilot.

Full implementation will expose:
- ``signalpilot analyze``  – run a full RCA for a namespace
- ``signalpilot watch``    – continuous watch mode with live updates
- ``signalpilot report``   – generate an HTML report from a saved analysis
- ``signalpilot gate``     – CI/CD gate command (exits non-zero on findings)
"""

from __future__ import annotations

import typer

app = typer.Typer(
    name="signalpilot",
    help="PerfSage SignalPilot – Kubernetes RCA copilot",
    no_args_is_help=True,
)


@app.command()
def analyze(
    namespace: str = typer.Option(..., "--namespace", "-n", help="Kubernetes namespace to analyse"),
    since: str = typer.Option("1h", "--since", help="Look-back window, e.g. 30m, 2h"),
    output: str = typer.Option("text", "--output", "-o", help="Output format: text|json|html"),
) -> None:
    """Run a full RCA analysis for *namespace*."""
    raise NotImplementedError


@app.command()
def watch(
    namespace: str = typer.Option(..., "--namespace", "-n", help="Kubernetes namespace to watch"),
) -> None:
    """Continuously monitor *namespace* and surface new findings in real time."""
    raise NotImplementedError


@app.command()
def report(
    analysis_id: str = typer.Argument(..., help="Analysis ID or path to saved JSON"),
    output: str = typer.Option("report.html", "--output", "-o", help="Output file path"),
) -> None:
    """Render an HTML report for a previously saved analysis."""
    raise NotImplementedError


@app.command()
def gate(
    namespace: str = typer.Option(..., "--namespace", "-n", help="Kubernetes namespace"),
    severity: str = typer.Option("high", "--severity", help="Minimum severity to fail: critical|high|medium|low"),
) -> None:
    """CI gate: exit 1 if any findings meet or exceed *severity*."""
    raise NotImplementedError
