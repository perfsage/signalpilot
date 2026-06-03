from typer.testing import CliRunner

from signalpilot.cli import app

runner = CliRunner()


class TestCli:
    def test_help(self) -> None:
        result = runner.invoke(app, ["--help"])
        assert result.exit_code == 0
        assert "analyze" in result.output

    def test_analyze_help(self) -> None:
        result = runner.invoke(app, ["analyze", "--help"])
        assert result.exit_code == 0
        assert "--deployment" in result.output

    def test_gate_help(self) -> None:
        result = runner.invoke(app, ["gate", "--help"])
        assert result.exit_code == 0

    def test_serve_help(self) -> None:
        result = runner.invoke(app, ["serve", "--help"])
        assert result.exit_code == 0
        assert "--host" in result.output

    def test_watch_help(self) -> None:
        result = runner.invoke(app, ["watch", "--help"])
        assert result.exit_code == 0
        assert "--interval" in result.output

    def test_verify_help(self) -> None:
        result = runner.invoke(app, ["verify", "--help"])
        assert result.exit_code == 0
        assert "--baseline-id" in result.output

    def test_gate_invalid_threshold(self) -> None:
        result = runner.invoke(app, ["gate", "default", "--threshold", "invalid"])
        assert result.exit_code == 2
