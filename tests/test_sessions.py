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
        monkeypatch.setattr(sessions.time, "strftime", lambda fmt, t=None, i=i: f"20261122-1200{i:02d}")
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
            else:  # the resumed agent goes on in the placed session
                placed = next((r.home / ".claude-config" / "projects").glob("*/*.jsonl"))
                with placed.open("a") as f:
                    f.write(json.dumps({"sessionId": placed.stem, "message": {"content": "said in the second room"}}) + "\n")
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
    monkeypatch.setattr(sessions.time, "strftime", lambda fmt, t=None: next(stamps))
    cli.main(["claude", "--project", str(tmp_path)])
    placed = []
    original = Claude.place_session
    monkeypatch.setattr(Claude, "place_session", lambda self, r, sid, lines: placed.append(
        (r.home, sid)) or original(self, r, sid, lines))
    cli.main(["claude", "--project", str(tmp_path), "--continue", "--", "--model", "haiku"])
    assert started[1] == ["claude", *AGENTS["claude"].room_flags, "--resume", "first-1", "--model", "haiku"]
    assert placed == [(tmp_path / "room-1", "first-1")]
    assert "continuing claude's session first-1" in capsys.readouterr().err
    # the resumed room's session is kept again, under the same id, with what the second room added
    first, second = sessions.kept()
    assert first.name.startswith("20261122-120000-") and second.name.startswith("20261122-120100-")
    assert first.name.endswith("-first-1.jsonl") and second.name.endswith("-first-1.jsonl")
    assert "said in the second room" in second.read_text() and "said in the second room" not in first.read_text()


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


def aged(path: Path, seconds: float = 2 * 86400):
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
        (r / "opt" / "agent").mkdir(parents=True)  # what a Seatbelt room holds
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
    backup = rooms_dir / "tare-room-backup"  # a folder of the user's that only looks like a room by name
    (backup / "photos").mkdir(parents=True)
    aged(backup)
    for r in (old, held, crashed):
        (r / ".claude-config").mkdir(parents=True)  # a bubblewrap room is the home itself
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
        assert not old.exists() and not crashed.exists() and not Path(f"{crashed}.lock").exists() and backup.exists()
        assert held.exists() and Path(f"{held}.lock").exists()
        assert sessions.kept() == [] and (outside / "keep.jsonl").exists()
        assert "2 rooms and 1 session removed" in capsys.readouterr().out
    finally:
        room._release(lock, held)


def test_a_copy_that_fails_half_way_leaves_no_session_to_continue_from(home, tmp_path, monkeypatch):
    r = Room(tmp_path / "room-home", tmp_path / "work")
    claude_session(r.home, "s1", "x")
    first = sessions.keep(Claude(), r, tmp_path / "project")

    def full(source, target):
        raise OSError(28, "No space left on device")
    monkeypatch.setattr(sessions.os, "replace", full)
    monkeypatch.setattr(sessions.time, "strftime", lambda fmt, t=None: "29991231-235959")
    with pytest.raises(OSError):
        sessions.keep(Claude(), r, tmp_path / "project")
    assert sessions.latest(Claude(), tmp_path / "project") == first
    assert sorted(p.name for p in first.parent.iterdir()) == [first.name]


def test_a_room_lock_is_held_under_its_name_from_the_start(rooms_dir):
    base = rooms_dir / "tare-room-new"
    base.mkdir()
    lock = room._hold(base)
    try:
        assert room.in_use(base) and sorted(p.name for p in rooms_dir.iterdir()) == ["tare-room-new", "tare-room-new.lock"]
    finally:
        lock.close()


def test_cleanup_removes_read_only_folders_and_says_what_it_could_not_remove(home, rooms_dir, monkeypatch, capsys):
    stuck, readonly = rooms_dir / "tare-room-stuck", rooms_dir / "tare-room-readonly"
    for r in (stuck, readonly):
        (r / "home").mkdir(parents=True)
    cache = readonly / "home" / "go" / "pkg" / "mod"
    cache.mkdir(parents=True)
    (cache / "module.go").write_text("package x")
    cache.chmod(0o555)
    for r in (stuck, readonly):
        aged(r)
        room._hold(r).close()  # crashed tares
    real_remove = room.remove_room
    monkeypatch.setattr(cli, "remove_room", lambda p: False if p == stuck else real_remove(p))
    assert cli.main(["cleanup"]) == 1
    assert not readonly.exists() and not Path(f"{readonly}.lock").exists()
    assert stuck.exists() and Path(f"{stuck}.lock").exists()  # found again next time
    captured = capsys.readouterr()
    assert f"could not remove  room  {stuck}" in captured.err and "1 room and 0 sessions removed" in captured.out


def test_a_link_in_the_room_never_brings_a_host_file_into_the_store(home, tmp_path):
    host = tmp_path / "host-transcript.jsonl"
    host.write_text(json.dumps({"sessionId": "host", "message": "the user's other conversation"}) + "\n")
    r = Room(tmp_path / "room-home", tmp_path / "work")
    link = r.home / ".claude-config" / "projects" / "-work" / "host.jsonl"
    link.parent.mkdir(parents=True)
    link.symlink_to(host)
    assert sessions.keep(Claude(), r, tmp_path / "project") is None
    linked_dir = r.home / ".claude-config" / "projects" / "-other"
    linked_dir.symlink_to(tmp_path)  # a linked folder, and the newest file through it
    assert sessions.keep(Claude(), r, tmp_path / "project") is None and sessions.kept() == []


def test_a_session_the_agent_never_extended_is_not_kept_again(home, tmp_path):
    r = Room(tmp_path / "room-home", tmp_path / "work")
    path = claude_session(r.home, "s1", "placed")
    placed = path.read_text().splitlines()
    assert sessions.keep(Claude(), r, tmp_path / "project", unless=placed) is None
    assert sessions.keep(Claude(), r, tmp_path / "project") is not None


def test_a_damaged_kept_session_is_refused(tmp_path):
    good = json.dumps({"sessionId": "s1"})
    (tmp_path / "half.jsonl").write_text(good + "\n" + '{"sessionId": "s1", "message": "cut off' + "\n")
    with pytest.raises(ValueError):
        sessions.read(tmp_path / "half.jsonl")
    (tmp_path / "bytes.jsonl").write_bytes(good.encode() + b"\n\xff\n")
    with pytest.raises(ValueError):
        sessions.read(tmp_path / "bytes.jsonl")


def test_a_link_in_the_store_is_refused_not_followed(home, tmp_path):
    outside = tmp_path / "outside"
    (outside / "x").mkdir(parents=True)
    (outside / "x" / "old.jsonl").write_text("not tare's")
    sessions.root().mkdir(parents=True)
    (sessions.root() / "claude").symlink_to(outside)
    r = Room(tmp_path / "room-home", tmp_path / "work")
    claude_session(r.home, "s1", "x")
    with pytest.raises(OSError, match="is a link"):
        sessions.keep(Claude(), r, tmp_path / "project")
    assert sessions.kept() == [] and sessions.latest(Claude(), tmp_path / "project") is None
    assert (outside / "x" / "old.jsonl").exists()


def test_pi_and_codex_resume_in_the_new_room_not_the_old_one(tmp_path):
    new = Room(tmp_path / "room-home", tmp_path / "work", inside_work="/private/tmp/tare-room-new/work")
    pi = [json.dumps({"type": "session", "id": "p1", "cwd": "/private/tmp/tare-room-old/work"}),
          json.dumps({"type": "message", "cwd": "/private/tmp/tare-room-old/work", "text": "kept as it was"})]
    Pi().place_session(new, "p1", pi)
    placed = next((new.config(Pi()) / "sessions").rglob("*.jsonl")).read_text().splitlines()
    assert json.loads(placed[0])["cwd"] == "/private/tmp/tare-room-new/work" and placed[1] == pi[1]
    codex = [json.dumps({"type": "session_meta", "payload": {"id": "x1", "cwd": "/private/tmp/tare-room-old/work"}})]
    Codex().place_session(new, "x1", codex)
    placed = next((new.config(Codex()) / "sessions").rglob("*-x1.jsonl")).read_text().splitlines()
    assert json.loads(placed[0])["payload"]["cwd"] == "/private/tmp/tare-room-new/work"


def test_a_room_whose_agent_still_runs_is_in_use_without_its_lock(rooms_dir, monkeypatch):
    r = rooms_dir / "tare-room-orphan"
    (r / "home").mkdir(parents=True)
    (r / "opt" / "agent").mkdir(parents=True)
    aged(r)
    room._hold(r).close()  # its tare was killed: the lock is free
    monkeypatch.setattr(room, "_room_processes", lambda base, sure=False: [4242] if base == r else [])
    assert room.leftover_rooms() == []


def test_a_pipe_in_place_of_the_session_does_not_hang_the_close(home, tmp_path):
    r = Room(tmp_path / "room-home", tmp_path / "work")
    path = r.home / ".claude-config" / "projects" / "-work" / "s1.jsonl"
    path.parent.mkdir(parents=True)
    os.mkfifo(path)
    assert sessions.keep(Claude(), r, tmp_path / "project") is None


def test_a_record_a_crash_cut_off_is_left_out_and_a_damaged_latest_is_passed_over(started, tmp_path, capsys):
    r = Room(tmp_path / "room-x", tmp_path / "work")
    path = claude_session(r.home, "s1", "whole")
    with path.open("a") as f:
        f.write('{"sessionId": "s1", "message": "cut o')
    kept = sessions.keep(Claude(), r, tmp_path)
    assert sessions.read(kept)[1] == [json.dumps({"sessionId": "s1", "message": {"content": "whole"}})]
    damaged = kept.parent / "99991231-235959-000000000-s2.jsonl"  # the latest, but not JSON
    damaged.write_text("not json\n")
    cli.main(["claude", "--project", str(tmp_path), "--continue"])
    err = capsys.readouterr().err
    assert f"cannot continue from {damaged}" in err and "continuing claude's session s1" in err


def test_a_pi_session_that_did_not_start_is_not_kept_again(home, tmp_path):
    header = json.dumps({"type": "session", "id": "p1", "cwd": "/old/work"})
    r = Room(tmp_path / "room-home", tmp_path / "work", inside_work="/new/work")
    placed = Pi().place_session(r, "p1", [header])
    assert json.loads(placed[0])["cwd"] == "/new/work"
    assert sessions.keep(Pi(), r, tmp_path / "project", unless=placed) is None


def test_an_id_that_pi_would_read_as_a_path_is_refused():
    assert sessions.session_id([json.dumps({"type": "session", "id": "review.jsonl"})]) is None


def test_kept_names_sort_by_time_in_utc_from_one_clock_read(home, tmp_path, monkeypatch):
    r = Room(tmp_path / "room-home", tmp_path / "work")
    claude_session(r.home, "s1", "x")
    clock = iter([1_799_999_999_999_999_999, 1_800_000_000_000_000_001])  # across a second's end
    monkeypatch.setattr(sessions.time, "time_ns", lambda: next(clock))
    first = sessions.keep(Claude(), r, tmp_path / "project")
    second = sessions.keep(Claude(), r, tmp_path / "project")
    assert sorted([second.name, first.name]) == [first.name, second.name]
    assert first.name.startswith(time.strftime("%Y%m%d-%H%M%S", time.gmtime(1_799_999_999)))


def test_cleanup_removes_only_old_half_written_copies(home, tmp_path):
    folder = sessions.store(Claude(), tmp_path / "project")
    folder.mkdir(parents=True)
    old, fresh = folder / ".a.jsonl.1.part", folder / ".b.jsonl.2.part"
    for p in (old, fresh):
        p.write_text("{")
    os.utime(old, (time.time() - 7200, time.time() - 7200))
    assert sessions.parts() == [old]


def test_cleanup_removes_copies_of_the_setup_a_killed_probe_left_and_nothing_fresh(home, rooms_dir, tmp_path, capsys):
    old, fresh = rooms_dir / "tare-copilot-twin-old", rooms_dir / "tare-pi-twin-fresh"
    for twin in (old, fresh):
        (twin / "copilot").mkdir(parents=True)
        (twin / "copilot" / "config.json").write_text("{}")
    aged(old, 2 * 3600)
    elsewhere = tmp_path / "precious"
    elsewhere.mkdir()
    (rooms_dir / "tare-agy-twin-link").symlink_to(elsewhere)
    assert room.leftover_twins() == [old]
    assert cli.main(["cleanup", "--dry-run"]) == 0 and old.exists()
    assert "0 rooms, 1 copy of your setup and 0 sessions would be removed" in capsys.readouterr().out
    assert cli.main(["cleanup"]) == 0
    assert not old.exists() and fresh.exists() and elsewhere.exists()
