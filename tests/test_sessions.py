"""Sessions kept when a room closes, resumed with --continue, removed by tare cleanup (epic #194)."""
import fcntl
import json
import os
import shutil
import time
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest

from tare import cli, room, sessions
from tare.agents import AGENTS, Claude, Codex, Pi
from tare.room import Room


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
    assert kept.parent == sessions.store(Claude(), tmp_path / "project")
    assert kept.name.endswith("-new.jsonl") and "after /clear" in kept.read_text()
    assert sessions.latest(Claude(), tmp_path / "project") == kept
    assert sessions.latest(Claude(), tmp_path / "other") is None


def test_the_store_is_the_users_alone(home, tmp_path):
    r = Room(tmp_path / "room-home", tmp_path / "work")
    claude_session(r.home, "s1", "x")
    kept = sessions.keep(Claude(), r, tmp_path / "project")
    assert oct(kept.stat().st_mode)[-3:] == "600"
    for folder in (sessions.root(), kept.parent.parent, kept.parent):
        assert oct(folder.stat().st_mode)[-3:] == "700"


def test_projects_whose_paths_look_alike_keep_their_sessions_apart(home, tmp_path):
    assert sessions.store(Claude(), tmp_path / "my-app") != sessions.store(Claude(), tmp_path / "my_app")
    assert sessions.store(Claude(), tmp_path / "my" / "app") != sessions.store(Claude(), tmp_path / "my-app")


def test_nothing_is_kept_without_a_session_a_safe_id_or_a_way_to_continue(home, tmp_path):
    r = Room(tmp_path / "room-home", tmp_path / "work")
    assert sessions.keep(Claude(), r, tmp_path) is None
    path = r.home / ".claude-config" / "projects" / "-work" / "x.jsonl"
    path.parent.mkdir(parents=True)
    path.write_text("not json\n{}\n")
    assert sessions.keep(Claude(), r, tmp_path) is None
    path.write_text(json.dumps({"sessionId": "../../outside"}) + "\n")
    assert sessions.keep(Claude(), r, tmp_path) is None
    claude_session(r.home, "s1", "x")
    agy_like = SimpleNamespace(name="agy", latest_session=Claude().latest_session)  # no continue_args
    assert sessions.keep(agy_like, r, tmp_path) is None


def test_kept_sessions_stay_until_cleanup(home, tmp_path, monkeypatch):
    r = Room(tmp_path / "room-home", tmp_path / "work")
    for i in range(25):
        claude_session(r.home, f"s{i:02d}", "x")
        monkeypatch.setattr(sessions.time, "strftime", lambda fmt, i=i: f"20261122-1200{i:02d}")
        sessions.keep(Claude(), r, tmp_path / "project")
    assert len(sessions.kept()) == 25


def test_the_session_id_of_each_agents_file_and_only_a_safe_one():
    assert sessions.session_id(['{"type": "summary"}', '{"sessionId": "c1"}']) == "c1"
    assert sessions.session_id(['{"type": "response_item", "payload": {"id": "msg_1"}}',
                                '{"type": "session_meta", "payload": {"id": "x1"}}']) == "x1"
    assert sessions.session_id(['{"type": "session", "id": "p1"}']) == "p1"
    assert sessions.session_id(["[1]", '{"id": "not a session"}', ""]) is None
    for unsafe in ("/tmp/evil", "../up", "-flag", ".hidden", "a/b", "x" * 200, "valid-id\n"):
        assert sessions.session_id([json.dumps({"sessionId": unsafe})]) is None


def test_a_line_separator_inside_a_json_string_survives_keeping_and_placing(home, tmp_path):
    r = Room(tmp_path / "room-home", tmp_path / "work", inside_work="/work")
    path = r.home / ".claude-config" / "projects" / "-work" / "s1.jsonl"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"sessionId": "s1", "text": "one\u2028two\u2029three"}, ensure_ascii=False) + "\n")
    kept = sessions.keep(Claude(), r, tmp_path / "project")
    sid, lines = sessions.read(kept)
    assert sid == "s1" and len(lines) == 1
    placed_room = Room(tmp_path / "room-2", tmp_path / "work", inside_work="/work")
    Claude().place_session(placed_room, sid, lines)
    placed = placed_room.home / ".claude-config" / "projects" / "-work" / "s1.jsonl"
    assert json.loads(placed.read_text())["text"] == "one\u2028two\u2029three"


def test_each_agent_resumes_interactively_with_its_own_arguments():
    assert Claude().continue_args("s") == ["--resume", "s"]
    assert Codex().continue_args("s") == ["resume", "s"]
    assert Pi().continue_args("s") == ["--session", "s"]
    assert not hasattr(AGENTS["agy"], "continue_args")


def test_codex_keeps_the_rollout_written_last(tmp_path):
    folder = tmp_path / ".codex" / "sessions" / "2026"
    resumed = folder / "01" / "01" / "rollout-2026-01-01T00-00-00-main.jsonl"
    other = folder / "11" / "22" / "rollout-2026-11-22T10-00-00-sub.jsonl"
    for path, when in ((other, time.time() - 60), (resumed, time.time())):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{}\n")
        os.utime(path, (when, when))
    assert Codex().latest_session(tmp_path) == resumed


@pytest.fixture
def started(monkeypatch, home, tmp_path):
    """tare claude with the probe, the login and the room stubbed. The room's home is removed when
    the room closes; a fresh start writes a session, a resumed one only what was placed."""
    runs = []
    monkeypatch.setattr(AGENTS["claude"], "discover", lambda: None)
    monkeypatch.setattr(cli, "probe", lambda *a: SimpleNamespace(zero=True))
    monkeypatch.setattr(cli, "render", lambda *a: "")

    class Rooms:
        def open(self, agent, real, project):
            @contextmanager
            def opened():
                home_dir = tmp_path / f"room-{len(runs)}"
                try:
                    yield Room(home_dir, project, inside_home="/home/tare", inside_work="/work")
                finally:
                    shutil.rmtree(home_dir, ignore_errors=True)
            return opened()

        def argv(self, r, agent, real, command):
            runs.append(command)
            if "--resume" not in command:
                claude_session(r.home, f"first-{len(runs)}", "written in the first room")
            return ["true"]

    monkeypatch.setattr(cli, "backend", lambda: Rooms())
    monkeypatch.setattr(cli, "_run_attached", lambda argv: 3)
    return runs


def test_a_room_keeps_its_session_before_it_is_removed_also_when_the_agent_fails(started, tmp_path, capsys):
    assert cli.main(["claude", "--project", str(tmp_path)]) == 3
    assert started == [["claude", *AGENTS["claude"].room_flags]]
    assert len(sessions.kept()) == 1 and "written in the first room" in sessions.kept()[0].read_text()
    assert "tare claude --continue" in capsys.readouterr().err


def test_continue_places_the_kept_session_and_resumes_it_before_the_users_arguments(started, tmp_path, capsys,
                                                                                    monkeypatch):
    stamps = iter(["20261122-120000", "20261122-120100"])
    monkeypatch.setattr(sessions.time, "strftime", lambda fmt: next(stamps))
    cli.main(["claude", "--project", str(tmp_path)])
    placed = []
    original = Claude.place_session
    monkeypatch.setattr(Claude, "place_session", lambda self, r, sid, lines: placed.append(
        (r.home, sid)) or original(self, r, sid, lines))
    cli.main(["claude", "--project", str(tmp_path), "--continue", "--", "--model", "haiku"])
    assert started[1] == ["claude", *AGENTS["claude"].room_flags, "--resume", "first-1", "--model", "haiku"]
    assert placed == [(tmp_path / "room-1", "first-1")]
    assert "continuing claude's session first-1" in capsys.readouterr().err
    # the resumed room's session is kept again, under the same id
    assert [p.name for p in sessions.kept()] == ["20261122-120000-first-1.jsonl", "20261122-120100-first-1.jsonl"]


def test_continue_without_a_usable_session_says_so_and_starts_nothing(started, tmp_path, capsys, monkeypatch):
    def no_probe(*a):
        raise AssertionError("the probe ran before the kept session was checked")
    monkeypatch.setattr(cli, "probe", no_probe)
    assert cli.main(["claude", "--project", str(tmp_path), "--continue"]) == 2
    assert started == [] and "no kept claude session" in capsys.readouterr().err
    broken = sessions.store(Claude(), tmp_path)
    broken.mkdir(parents=True)
    (broken / "20261122-120000-x.jsonl").write_text("not a session\n")
    assert cli.main(["claude", "--project", str(tmp_path), "--continue"]) == 2
    assert started == [] and "cannot continue from" in capsys.readouterr().err


def test_an_agent_that_cannot_resume_says_so(started, tmp_path, capsys):
    assert cli.main(["agy", "--project", str(tmp_path), "--continue"]) == 2
    assert "agy cannot continue a session yet" in capsys.readouterr().err


def test_a_failure_to_keep_the_session_does_not_replace_the_agents_exit(started, tmp_path, capsys, monkeypatch):
    def broken(*a):
        raise OSError("disk full")
    monkeypatch.setattr(sessions, "keep", broken)
    assert cli.main(["claude", "--project", str(tmp_path)]) == 3
    assert "could not keep the session: OSError: disk full" in capsys.readouterr().err


@pytest.fixture
def rooms_dir(monkeypatch, tmp_path):
    """Seatbelt's rooms and the temporary directory, both in tmp_path."""
    place = tmp_path / "rooms"
    place.mkdir()
    monkeypatch.setattr(room, "SEATBELT_ROOMS", str(place))
    monkeypatch.setattr(room.tempfile, "gettempdir", lambda: str(place))
    return place.resolve()


def aged(path: Path, seconds: float = 7200):
    when = time.time() - seconds
    for directory, dirs, files in os.walk(path):
        for name in [*dirs, *files]:
            os.utime(os.path.join(directory, name), (when, when), follow_symlinks=False)
    os.utime(path, (when, when))


def test_only_the_users_own_room_folders_are_rooms_never_a_link(rooms_dir, tmp_path):
    (rooms_dir / "tare-room-a" / "home").mkdir(parents=True)
    elsewhere = tmp_path / "precious"
    elsewhere.mkdir()
    (rooms_dir / "tare-room-link").symlink_to(elsewhere)
    (rooms_dir / "tare-room-file").write_text("x")
    (rooms_dir / "other").mkdir()
    assert room.rooms_on_disk() == [rooms_dir / "tare-room-a"]


def test_a_room_is_in_use_while_its_lock_is_held_and_left_over_once_it_is_free(rooms_dir):
    held, free, legacy_busy, legacy_idle = (rooms_dir / f"tare-room-{n}" for n in ("held", "free", "busy", "idle"))
    for r in (held, free, legacy_busy, legacy_idle):
        (r / "home").mkdir(parents=True)
        aged(r)
    lock = room._hold(held)  # a running tare, however old its room
    room._hold(free).close()  # its tare crashed: the lock file is there, the lock is free
    (legacy_busy / "home" / "session.jsonl").write_text("written just now")  # a tare 0.5.0 room in use
    try:
        assert room.leftover_rooms() == [free, legacy_idle]
        lock.close()  # the running tare crashes too
        assert room.leftover_rooms() == [free, held, legacy_idle]
    finally:
        lock.close()


def test_a_lock_tare_did_not_make_keeps_the_room(rooms_dir, tmp_path):
    linked, piped, foreign_target = rooms_dir / "tare-room-linked", rooms_dir / "tare-room-piped", tmp_path / "x"
    for r in (linked, piped):
        (r / "home").mkdir(parents=True)
        aged(r)
    foreign_target.write_text("")
    Path(f"{linked}.lock").symlink_to(foreign_target)  # planted by someone else in /tmp
    os.mkfifo(f"{piped}.lock")  # would block an open()
    assert room.leftover_rooms() == []
    with pytest.raises(room.TareError, match="cannot lock the room"):
        room._hold(linked)
    room.remove_lock(linked)
    assert Path(f"{linked}.lock").is_symlink() and foreign_target.exists()


def test_a_bubblewrap_and_a_seatbelt_room_hold_their_lock_until_they_are_gone(rooms_dir, tmp_path, monkeypatch):
    seen = {}

    class Tool:
        name, config_dir = "tool", ".tool"

        def token_lifetime(self, real):
            return float("inf")

        def seed(self, real, config, r):
            pass

        def binds(self, real):
            return [], "/bin/true"

    for backend in (room.Bubblewrap(), room.Seatbelt()):
        monkeypatch.setattr(room, "_developer_bin", lambda: [])
        work = tmp_path / "work"
        work.mkdir(exist_ok=True)
        with backend.open(Tool(), SimpleNamespace(), work) as r:
            base = r.home if isinstance(backend, room.Bubblewrap) else r.home.parent
            seen[type(backend).__name__] = (room.in_use(base), Path(f"{base}.lock").exists())
        assert not base.exists() and not Path(f"{base}.lock").exists()
    assert seen == {"Bubblewrap": (True, True), "Seatbelt": (True, True)}


def test_cleanup_removes_leftover_rooms_and_kept_sessions_and_nothing_else(home, rooms_dir, tmp_path, capsys):
    old, held, crashed = rooms_dir / "tare-room-old", rooms_dir / "tare-room-held", rooms_dir / "tare-room-crashed"
    for r in (old, held, crashed):
        (r / "home").mkdir(parents=True)
        aged(r)
    lock = room._hold(held)
    room._hold(crashed).close()
    r = Room(tmp_path / "room-home", tmp_path / "work")
    claude_session(r.home, "s1", "x")
    sessions.keep(Claude(), r, tmp_path / "project")
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "keep.jsonl").write_text("not tare's")
    (sessions.root() / "linked").symlink_to(outside)  # a link in the store is not followed

    try:
        assert cli.main(["cleanup", "--dry-run"]) == 0
        assert old.exists() and crashed.exists() and len(sessions.kept()) == 1
        assert "2 rooms and 1 session would be removed" in capsys.readouterr().out

        assert cli.main(["cleanup"]) == 0
        assert not old.exists() and not crashed.exists() and not Path(f"{crashed}.lock").exists()
        assert held.exists() and Path(f"{held}.lock").exists()
        assert sessions.kept() == [] and (outside / "keep.jsonl").exists()
        assert "2 rooms and 1 session removed" in capsys.readouterr().out
    finally:
        room._release(lock, held)
