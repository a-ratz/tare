"""Sessions kept when a room closes, resumed with --continue, removed by tare cleanup (epic #194)."""
import json
import os
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from tare import cli, room, sessions
from tare.agents import AGENTS, Claude, Codex, Pi
from tare.room import Room, TareError


@pytest.fixture
def home(monkeypatch, tmp_path):
    """The user's home, where the store lives."""
    h = tmp_path / "user"
    h.mkdir()
    monkeypatch.setenv("HOME", str(h))
    return h


def claude_session(room_home: Path, sid: str, text: str, key: str = "-work", when: float | None = None) -> Path:
    path = room_home / ".claude-config" / "projects" / key / f"{sid}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"sessionId": sid, "message": {"content": text}}) + "\n")
    if when:
        os.utime(path, (when, when))
    return path


def test_a_closing_room_keeps_the_latest_session_by_agent_and_project(home, tmp_path):
    r = Room(tmp_path / "room-home", tmp_path / "work")
    claude_session(r.home, "old", "before /clear", when=time.time() - 60)
    claude_session(r.home, "new", "after /clear")
    sub = r.home / ".claude-config" / "projects" / "-work" / "new" / "subagents" / "agent-1.jsonl"
    sub.parent.mkdir(parents=True)
    sub.write_text(json.dumps({"sessionId": "sub", "pad": "x" * 5000}) + "\n")  # larger, deeper, newer
    kept = sessions.keep(Claude(), r, tmp_path / "project")
    assert kept.parent == home / ".local/state/tare/sessions/claude" / sessions.store(Claude(), tmp_path / "project").name
    assert kept.name.endswith("-new.jsonl") and "after /clear" in kept.read_text()
    assert oct(kept.stat().st_mode)[-3:] == "600"
    assert sessions.latest(Claude(), tmp_path / "project") == kept
    assert sessions.latest(Claude(), tmp_path / "other") is None


def test_nothing_is_kept_without_a_session_or_its_id(home, tmp_path):
    r = Room(tmp_path / "room-home", tmp_path / "work")
    assert sessions.keep(Claude(), r, tmp_path) is None
    path = r.home / ".claude-config" / "projects" / "-work" / "x.jsonl"
    path.parent.mkdir(parents=True)
    path.write_text("not json\n{}\n")
    assert sessions.keep(Claude(), r, tmp_path) is None
    assert sessions.keep(SimpleNamespace(name="tool"), r, tmp_path) is None  # an agent that keeps no sessions


def test_kept_sessions_stay_until_cleanup(home, tmp_path, monkeypatch):
    r = Room(tmp_path / "room-home", tmp_path / "work")
    for i in range(25):
        claude_session(r.home, f"s{i:02d}", "x")
        monkeypatch.setattr(sessions.time, "strftime", lambda fmt, i=i: f"20261122-1200{i:02d}")
        sessions.keep(Claude(), r, tmp_path / "project")
    assert len(sessions.kept()) == 25


def test_the_session_id_of_each_agents_file():
    assert sessions.session_id(['{"type": "summary"}', '{"sessionId": "c1"}']) == "c1"
    assert sessions.session_id(['{"type": "session_meta", "payload": {"id": "x1"}}']) == "x1"
    assert sessions.session_id(['{"type": "session", "id": "p1"}']) == "p1"
    assert sessions.session_id(["[1]", '{"id": "not a session"}', ""]) is None


def test_each_agent_resumes_interactively_with_its_own_arguments():
    assert Claude().continue_args("s") == ["--resume", "s"]
    assert Codex().continue_args("s") == ["resume", "s"]
    assert Pi().continue_args("s") == ["--session", "s"]
    assert not hasattr(AGENTS["agy"], "continue_args")


@pytest.fixture
def started(monkeypatch, home, tmp_path):
    """tare claude with the probe, the login and the room stubbed: records the command the room would run."""
    runs = []
    monkeypatch.setattr(AGENTS["claude"], "discover", lambda: None)
    monkeypatch.setattr(cli, "probe", lambda *a: SimpleNamespace(zero=True))
    monkeypatch.setattr(cli, "render", lambda *a: "")

    class Rooms:
        def open(self, agent, real, project):
            from contextlib import contextmanager

            @contextmanager
            def opened():
                yield Room(tmp_path / "room-home", project, inside_home="/home/tare", inside_work="/work")
            return opened()

        def argv(self, r, agent, real, command):
            runs.append(command)
            claude_session(r.home, "fresh-or-resumed", "written in the room")  # what the agent leaves
            return ["true"]

    monkeypatch.setattr(cli, "backend", lambda: Rooms())
    monkeypatch.setattr(cli, "_run_attached", lambda argv: 3)
    return runs


def test_a_room_keeps_its_session_also_when_the_agent_fails(started, tmp_path, capsys):
    assert cli.main(["claude", "--project", str(tmp_path)]) == 3
    assert started == [["claude", *AGENTS["claude"].room_flags]]
    assert len(sessions.kept()) == 1
    assert "tare claude --continue" in capsys.readouterr().err


def test_continue_places_the_latest_session_and_resumes_it_before_the_users_arguments(started, tmp_path, capsys):
    cli.main(["claude", "--project", str(tmp_path)])
    cli.main(["claude", "--project", str(tmp_path), "--continue", "--", "--model", "haiku"])
    assert started[1] == ["claude", *AGENTS["claude"].room_flags, "--resume", "fresh-or-resumed", "--model", "haiku"]
    placed = tmp_path / "room-home" / ".claude-config" / "projects" / "-work" / "fresh-or-resumed.jsonl"
    assert "written in the room" in placed.read_text()
    assert "continuing claude's session fresh-or-resumed" in capsys.readouterr().err


def test_continue_without_a_kept_session_says_so_and_starts_nothing(started, tmp_path, capsys):
    assert cli.main(["claude", "--project", str(tmp_path), "--continue"]) == 2
    assert started == [] and "no kept claude session" in capsys.readouterr().err


def test_an_agent_that_cannot_resume_says_so(started, tmp_path, capsys):
    assert cli.main(["agy", "--project", str(tmp_path), "--continue"]) == 2
    assert "agy cannot continue a session yet" in capsys.readouterr().err


def test_cleanup_removes_leftover_rooms_and_kept_sessions_and_spares_rooms_in_use(home, tmp_path, monkeypatch, capsys):
    rooms = tmp_path / "rooms"
    old, busy, fresh = rooms / "tare-room-old", rooms / "tare-room-busy", rooms / "tare-room-fresh"
    for r in (old, busy, fresh):
        (r / "home").mkdir(parents=True)
    long_ago = time.time() - 3600
    for r in (old, busy):
        os.utime(r, (long_ago, long_ago))
    monkeypatch.setattr(room, "rooms_on_disk", lambda: [old, busy, fresh])
    monkeypatch.setattr(room.subprocess, "run", lambda *a, **k: SimpleNamespace(stdout=f"/usr/bin/sandbox-exec -p ... {busy}/opt/agent/claude\n"))
    r = Room(tmp_path / "room-home", tmp_path / "work")
    claude_session(r.home, "s1", "x")
    sessions.keep(Claude(), r, tmp_path / "project")

    assert cli.main(["cleanup", "--dry-run"]) == 0
    assert old.exists() and len(sessions.kept()) == 1
    assert "1 room and 1 session would be removed" in capsys.readouterr().out

    assert cli.main(["cleanup"]) == 0
    assert not old.exists() and busy.exists() and fresh.exists()
    assert sessions.kept() == [] and not any((home / ".local/state/tare/sessions/claude").iterdir())
    assert "1 room and 1 session removed" in capsys.readouterr().out
