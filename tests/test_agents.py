import pytest

from tare import agents
from tare.agents import AGENTS
from tare.room import TareError


def test_a_resumed_claude_tail_streams_events_like_a_fresh_start():
    claude = AGENTS["claude"]
    fresh = claude.run_args("task", [])
    resumed = claude.resume_args("session", "Continue.", [])
    for flag in ("--output-format", "stream-json", "--verbose"):
        assert flag in fresh and flag in resumed


def mise_shim(tmp_path, script):
    """A stand-in for mise and a shim that links to it, the way `mise` sets up `claude` on PATH."""
    mise = tmp_path / "bin/mise"
    mise.parent.mkdir()
    mise.write_text(f"#!/bin/sh\n{script}\n")
    mise.chmod(0o755)
    shim = tmp_path / "shims/claude"
    shim.parent.mkdir()
    shim.symlink_to(mise)
    return mise, shim


def test_which_finds_the_program_behind_a_mise_shim(tmp_path, monkeypatch):
    tool = tmp_path / "installs/claude/2.1.325/claude"
    tool.parent.mkdir(parents=True)
    tool.write_text("")
    _, shim = mise_shim(tmp_path, f'[ "$1" = which ] && [ "$2" = claude ] && echo "{tool}"')
    monkeypatch.setattr(agents.shutil, "which", lambda name: str(shim))
    assert agents._which("claude") == tool


def test_which_names_the_shim_when_mise_does_not_know_the_program(tmp_path, monkeypatch):
    _, shim = mise_shim(tmp_path, "echo 'mise ERROR claude is not installed' >&2; exit 1")
    monkeypatch.setattr(agents.shutil, "which", lambda name: str(shim))
    with pytest.raises(TareError, match="mise shim .*first on PATH"):
        agents._which("claude")


def test_which_leaves_mise_itself_and_other_links_alone(tmp_path, monkeypatch):
    mise, _ = mise_shim(tmp_path, "exit 1")
    monkeypatch.setattr(agents.shutil, "which", lambda name: str(mise))
    assert agents._which("mise") == mise
    program = tmp_path / "opt/claude"
    program.parent.mkdir()
    program.write_text("")
    link = tmp_path / "link/claude"
    link.parent.mkdir()
    link.symlink_to(program)
    monkeypatch.setattr(agents.shutil, "which", lambda name: str(link))
    assert agents._which("claude") == program
