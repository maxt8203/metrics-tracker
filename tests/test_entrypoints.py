"""Every module imports and every CLI command exists."""

import importlib

import pytest

from tracker import cli

MODULES = [
    "tracker.cli",
    "tracker.pipeline",
    "tracker.timesplit",
    "tracker.charts",
    "tracker.sources.oura",
    "tracker.sources.gcal",
    "tracker.sources.classifier",
    "tracker.sources.oauth_local",
    "agent.review_agent",
    "tests.agent_evals.run_evals",
    "demo.run_demo",
]

# Exact names: README and Makefile refer to these.
CLI_COMMANDS = ["auth", "probe-oura", "pull", "checkin", "summary", "chart", "review"]


@pytest.mark.parametrize("name", MODULES)
def test_module_imports(name):
    importlib.import_module(name)


def test_cli_commands_exist(capsys):
    with pytest.raises(SystemExit):
        cli.main(["--help"])
    out = capsys.readouterr().out
    for cmd in CLI_COMMANDS:
        assert cmd in out, f"missing CLI command: {cmd}"


def test_summary_runs_on_empty_store(tmp_path, capsys):
    cli.main(["--data-dir", str(tmp_path), "summary"])
    assert "No weeks stored yet" in capsys.readouterr().out


def test_chart_command_writes_html(tmp_path):
    out = tmp_path / "c.html"
    cli.main(["--data-dir", str(tmp_path), "chart", "--out", str(out)])
    assert out.exists() and "<html" in out.read_text()
