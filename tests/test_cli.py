"""The command line: renamed flags work under their plain names and their old ones (epic #135)."""
from types import SimpleNamespace

import pytest

from tare import cli
from tare.agents import AGENTS


@pytest.fixture
def captured(monkeypatch):
    """Runs nothing: discovery, the probe, the dashboard and the moves are stubs that record their arguments."""
    calls = {}
    for agent in AGENTS.values():
        monkeypatch.setattr(agent, "discover", lambda: None)
    monkeypatch.setattr(cli, "probe", lambda *a: SimpleNamespace(zero=True))
    monkeypatch.setattr(cli, "render", lambda *a: "")
    monkeypatch.setattr(cli, "_serve", lambda *a: "")
    monkeypatch.setattr(cli.recipe, "write", lambda *a, **k: None)
    monkeypatch.setattr(cli, "cliff", lambda *a, **k: calls.update(cliff=k) or "")
    monkeypatch.setattr(cli, "swap", lambda *a, **k: calls.update(swap=k) or "")
    return calls


def _run(tmp_path, *args):
    return cli.main([*args, "--check", "true", "--project", str(tmp_path), "--out", str(tmp_path / "out")])


@pytest.mark.parametrize("flags", [["--restarts", "5", "--too-hard-below", "0.1"], ["--tails", "5", "--gap-below", "0.1"]])
def test_cliff_takes_the_plain_flags_and_the_old_names(captured, tmp_path, flags):
    assert _run(tmp_path, "cliff", "claude", "the task", *flags) == 0
    assert (captured["cliff"]["tails"], captured["cliff"]["gap_below"]) == (5, 0.1)


@pytest.mark.parametrize("flags, workspace_only", [
    (["--handovers", "0,1", "--restarts", "2", "--handover", "workspace"], True),
    (["--cuts", "0,1", "--tails", "2", "--handoff", "trail"], False),
])
def test_swap_takes_the_plain_flags_and_the_old_names(captured, tmp_path, flags, workspace_only):
    assert _run(tmp_path, "swap", "the task", *flags) == 0
    assert captured["swap"]["cuts"] == [0.0, 1.0]
    assert (captured["swap"]["tails"], captured["swap"]["workspace_only"]) == (2, workspace_only)


def test_the_defaults_hold_without_these_flags(captured, tmp_path):
    _run(tmp_path, "cliff", "claude", "the task")
    assert (captured["cliff"]["tails"], captured["cliff"]["gap_below"]) == (3, 0.2)


def test_help_shows_only_the_plain_names(capsys):
    for command in ("cliff", "swap"):
        with pytest.raises(SystemExit):
            cli.main([command, "--help"])
        shown = capsys.readouterr().out
        assert "--restarts" in shown
        assert not any(old in shown for old in ("--tails", "--cuts", "--handoff", "--gap-below"))
