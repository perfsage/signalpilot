import re

from typer.testing import CliRunner

from signalpilot.cli import app

runner = CliRunner()


def _strip_ansi(text: str) -> str:
    """Remove ANSI escape codes so assertions work regardless of Rich version."""
    return re.sub(r"\x1b\[[0-9;]*m", "", text)


class TestCli:
    def test_help(self) -> None:
        result = runner.invoke(app, ["--help"])
        assert result.exit_code == 0
        assert "analyze" in _strip_ansi(result.output)

    def test_analyze_help(self) -> None:
        result = runner.invoke(app, ["analyze", "--help"])
        assert result.exit_code == 0
        out = _strip_ansi(result.output)
        # Check option names survive stripping (typer renders as --deployment or -d)
        assert "deployment" in out
        assert "namespace" in out

    def test_gate_help(self) -> None:
        result = runner.invoke(app, ["gate", "--help"])
        assert result.exit_code == 0

    def test_serve_help(self) -> None:
        result = runner.invoke(app, ["serve", "--help"])
        assert result.exit_code == 0
        assert "host" in _strip_ansi(result.output)

    def test_watch_help(self) -> None:
        result = runner.invoke(app, ["watch", "--help"])
        assert result.exit_code == 0
        assert "interval" in _strip_ansi(result.output)

    def test_verify_help(self) -> None:
        result = runner.invoke(app, ["verify", "--help"])
        assert result.exit_code == 0
        assert "baseline" in _strip_ansi(result.output)

    def test_gate_invalid_threshold(self) -> None:
        result = runner.invoke(app, ["gate", "default", "--threshold", "invalid"])
        assert result.exit_code == 2
