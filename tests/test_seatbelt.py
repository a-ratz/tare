import json
import os
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest

from conftest import HOST
from tare import agents, probe, room
from tare.agents import Claude, Codex, Pi, Real
from tare.room import Room, Seatbelt, TareError

REAL_END = room._end_processes


@pytest.fixture
def mac(monkeypatch, tmp_path):
    """macOS as Seatbelt sees it, with the rooms under tmp_path."""
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(room, "SEATBELT_ROOMS", str(tmp_path / "rooms"))
    monkeypatch.setattr(room, "_user_dir", lambda: Path("/private/var/folders/xy/user"))
    monkeypatch.setattr(probe, "_user_dir", room._user_dir)
    monkeypatch.setattr(room, "_developer_bin", lambda: ["/Library/Developer/CommandLineTools/usr/bin"])
    monkeypatch.setattr(room, "_end_processes", lambda base, grace=3.0: 0)  # no ps or lsof in unit tests
    (tmp_path / "rooms").mkdir()
    return tmp_path


def login(expires_in=7200):
    return json.dumps({"claudeAiOauth": {"accessToken": "a", "refreshToken": "r",
                                         "expiresAt": (time.time() + expires_in) * 1000}})


def claude_on_mac(tmp_path, monkeypatch, keychain: str | None = ""):
    keychain = login() if keychain == "" else keychain
    asked = []
    monkeypatch.setattr(agents, "_security", lambda account, service: asked.append((account, service)) or keychain)
    binary = tmp_path / "versions" / "2.1.289"
    binary.parent.mkdir()
    binary.write_text("#!/bin/sh\n")
    (tmp_path / ".claude").mkdir()
    return Real(home=tmp_path, config=tmp_path / ".claude", binary=binary), asked


def project(tmp_path) -> Path:
    work = tmp_path / "project"
    (work / "src").mkdir(parents=True)
    (work / "src" / "keep.py").write_text("keep\n")
    (work / "src" / "change.py").write_text("old\n")
    (work / "gone.txt").write_text("gone\n")
    return work


def test_claude_takes_its_login_from_the_keychain_on_macos(tmp_path, monkeypatch, mac):
    monkeypatch.setenv("USER", "ara")
    monkeypatch.delenv("CLAUDE_CONFIG_DIR", raising=False)
    real, asked = claude_on_mac(tmp_path, monkeypatch)
    assert 7000 < Claude().token_lifetime(real) < 7300
    assert asked[0] == ("ara", "Claude Code-credentials")
    assert Claude().billing(real) == "subscription"


def test_the_keychain_service_follows_claude_config_dir(monkeypatch):
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", "/Users/ara/.claude-work")
    monkeypatch.setenv("USER", "name with space")
    account, service = Claude().keychain_item()
    assert account == "claude-code-user"
    assert service.startswith("Claude Code-credentials-") and len(service) == len("Claude Code-credentials-") + 8


def test_no_login_on_macos_names_the_keychain_item(tmp_path, monkeypatch, mac):
    real, _ = claude_on_mac(tmp_path, monkeypatch, keychain=None)
    with pytest.raises(TareError, match=r"Keychain \(Claude Code-credentials"):
        Claude().token_lifetime(real)


def test_seatbelt_room_holds_clones_and_a_login_copy_and_is_removed(tmp_path, monkeypatch, mac):
    secret = login()
    real, _ = claude_on_mac(tmp_path, monkeypatch, secret)
    work = project(tmp_path)
    with Seatbelt().open(Claude(), real, work) as r:
        base = r.home.parent
        assert base.parent == tmp_path / "rooms"
        assert (base / "opt/agent/claude").read_text() == "#!/bin/sh\n"
        assert (base / "work/src/keep.py").read_text() == "keep\n"
        creds = r.config(Claude()) / ".credentials.json"
        assert creds.read_text() == secret
        assert oct(creds.stat().st_mode & 0o777) == "0o600"
        trusted = json.loads((r.config(Claude()) / ".claude.json").read_text())["projects"]
        assert list(trusted) == [str(base / "work")]
        assert (r.inside_home, r.inside_work) == (str(base / "home"), str(base / "work"))
    assert not base.exists()


def test_seatbelt_copies_the_runs_changes_back_and_leaves_the_rest(tmp_path, monkeypatch, mac):
    real, _ = claude_on_mac(tmp_path, monkeypatch)
    work = project(tmp_path)
    with Seatbelt().open(Claude(), real, work) as r:
        clone = Path(r.inside_work)
        (clone / "src" / "change.py").write_text("new\n")
        (clone / "gone.txt").unlink()
        (clone / "new" / "deep").mkdir(parents=True)
        (clone / "new" / "deep" / "file.txt").write_text("added\n")
        (clone / "link").symlink_to("src/keep.py")
        (work / "src" / "keep.py").write_text("the user's edit meanwhile\n")
    assert (work / "src" / "change.py").read_text() == "new\n"
    assert not (work / "gone.txt").exists()
    assert (work / "new" / "deep" / "file.txt").read_text() == "added\n"
    assert os.readlink(work / "link") == "src/keep.py"
    assert (work / "src" / "keep.py").read_text() == "the user's edit meanwhile\n"


def test_seatbelt_copy_back_leaves_out_sockets_and_pipes_and_copies_the_rest(tmp_path, monkeypatch, mac):
    real, _ = claude_on_mac(tmp_path, monkeypatch)
    work = project(tmp_path)
    (work / ".git").mkdir()
    os.mkfifo(work / "old-pipe")  # in the project before the run, which removes it
    with Seatbelt().open(Claude(), real, work) as r:
        clone = Path(r.inside_work)
        (clone / "old-pipe").unlink()
        server = socket.socket(socket.AF_UNIX)  # as git's fsmonitor keeps one in .git
        monkeypatch.chdir(clone / ".git")  # a socket's path has room for about 100 bytes
        server.bind("fsmonitor--daemon.ipc")
        monkeypatch.chdir(tmp_path)
        os.mkfifo(clone / "pipe")
        (clone / "gone.txt").unlink()
        os.mkfifo(clone / "gone.txt")  # a file the run replaced with a pipe
        (clone / "z-after.txt").write_text("after the socket\n")
    server.close()
    assert (work / "z-after.txt").read_text() == "after the socket\n"
    assert not (work / ".git" / "fsmonitor--daemon.ipc").exists() and not (work / "pipe").exists()
    assert not (work / "gone.txt").exists() and not (work / "old-pipe").exists()


def test_seatbelt_argv_clears_the_environment_and_runs_the_clone_in_the_work_clone(tmp_path, monkeypatch, mac):
    real, _ = claude_on_mac(tmp_path, monkeypatch)
    with Seatbelt().open(Claude(), real, project(tmp_path)) as r:
        base = r.home.parent
        argv = Seatbelt().argv(r, Claude(), real, ["claude", "-p", "hi"], {"ANTHROPIC_BASE_URL": "http://fake"})
    assert argv[:4] == ["/bin/sh", "-c", 'cd "$0" && exec "$@"', str(base / "work")]
    assert argv[4:6] == ["/usr/bin/env", "-i"]
    env = dict(a.split("=", 1) for a in argv[6:argv.index("/usr/bin/sandbox-exec")])
    assert env["HOME"] == str(base / "home")
    assert env["PATH"] == f"{base}/opt/agent:/Library/Developer/CommandLineTools/usr/bin:/usr/bin:/bin"
    assert env["TMPDIR"] == env["CLAUDE_CODE_TMPDIR"] == env["MAC_CHROMIUM_TMPDIR"] == str(base / "tmp")
    assert env["AGENT_BROWSER_ARGS"] == "--no-sandbox"
    assert env["CLAUDE_CONFIG_DIR"] == str(base / "home/.claude-config")
    assert env["ANTHROPIC_BASE_URL"] == "http://fake"
    assert argv[-3:] == [f"{base}/opt/agent/claude", "-p", "hi"]


def test_seatbelt_profile_denies_the_home_and_shared_places_and_allows_the_room(tmp_path, mac):
    base = tmp_path / "rooms" / "tare-room-x"
    text = room.profile(Room(base / "home", tmp_path / "w", tmp_path / "run", inside_run=str(tmp_path / "run")))
    deny = next(line for line in text.splitlines() if line.startswith("(deny file-read* file-write*"))
    for path in (str(Path.home().resolve()), "/private/var/folders/xy/user", "/private/tmp", "/private/var/tmp",
                 "/Users/Shared"):
        assert f'(subpath "{path}")' in deny
    assert '(deny mach-lookup (global-name "com.apple.pasteboard.1"))' in text
    lines = text.splitlines()
    allow = lines.index(f'(allow file-read* file-write* (subpath "{base}"))')
    assert lines.index(deny) < allow < lines.index(f'(deny file-write* (subpath "{base}/opt"))')
    assert f'(allow file-read* file-write* (subpath "{tmp_path / "run"}"))' in lines
    # writes go nowhere outside the room but the devices; the room and the run's store come after
    no_writes = lines.index('(deny file-write* (subpath "/"))')
    assert no_writes < lines.index('(allow file-write* (subpath "/dev"))') < allow
    assert lines[no_writes - 1] == "(allow default)"
    assert lines.index(deny) < lines.index(f'(allow file-read* file-write* (subpath "{tmp_path / "run"}"))')


def test_the_developer_tools_are_on_the_path_only_where_xcode_select_names_them(tmp_path, monkeypatch):
    tools = tmp_path / "Developer" / "usr" / "bin"
    tools.mkdir(parents=True)
    monkeypatch.setattr(room, "_denied", lambda: (tmp_path / "home",))
    calls = []
    answer = lambda out, code=0: lambda *a, **k: calls.append(k.get("env")) or subprocess.CompletedProcess(a, code, out, "")
    monkeypatch.setattr(room.subprocess, "run", answer(f"{tmp_path / 'Developer'}\n"))
    assert room._developer_bin() == [str(tools.resolve())]
    assert calls == [{}]  # the system's choice, not the caller's DEVELOPER_DIR
    monkeypatch.setattr(room.subprocess, "run", answer(f"{tmp_path / 'gone'}\n"))
    assert room._developer_bin() == []
    monkeypatch.setattr(room.subprocess, "run", answer(""))  # no developer directory selected
    assert room._developer_bin() == []
    monkeypatch.setattr(room.subprocess, "run", answer(f"{tmp_path / 'Developer'}\n", 2))  # xcode-select failed
    assert room._developer_bin() == []
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(room.subprocess, "run", answer("Developer\n"))  # relative
    assert room._developer_bin() == []
    (tmp_path / "home" / "Xcode" / "usr" / "bin").mkdir(parents=True)  # in a place the room denies
    monkeypatch.setattr(room.subprocess, "run", answer(f"{tmp_path / 'home' / 'Xcode'}\n"))
    assert room._developer_bin() == []
    (tmp_path / "home" / "link").symlink_to(tmp_path / "Developer")  # through a denied place to an allowed one
    monkeypatch.setattr(room.subprocess, "run", answer(f"{tmp_path / 'home' / 'link'}\n"))
    assert room._developer_bin() == [str(tools.resolve())]

    def missing(*a, **k):
        raise FileNotFoundError("xcode-select")
    monkeypatch.setattr(room.subprocess, "run", missing)
    assert room._developer_bin() == []


def test_seatbelt_profile_allows_the_runs_store_by_its_resolved_path(tmp_path, mac):
    (tmp_path / "store").mkdir()
    (tmp_path / "link").symlink_to(tmp_path / "store")  # as /var/folders is a link to /private/var/folders
    text = room.profile(Room(tmp_path / "rooms/r/home", tmp_path / "w", tmp_path / "link"))
    assert f'(subpath "{(tmp_path / "store").resolve()}")' in text and str(tmp_path / "link") not in text


def test_codex_and_pi_are_cloned_from_the_home_on_macos(tmp_path, monkeypatch, mac):
    release = tmp_path / ".codex/packages/standalone/releases/0.159.0-aarch64-apple-darwin"
    real = Real(tmp_path, tmp_path / ".codex", release / "bin" / "codex")
    assert Codex().binds(real) == (["--ro-bind", str(release), "/opt/agent/codex"], "/opt/agent/codex/bin/codex")
    package = tmp_path / ".local/lib/node_modules/@earendil-works/pi-coding-agent"
    monkeypatch.setattr(agents, "_which", lambda name: tmp_path / "node/bin/node")
    binds, executable = Pi().binds(Real(tmp_path, tmp_path / ".pi/agent", package / "dist/bundle/cli.js"))
    assert binds == ["--ro-bind", str(package), "/opt/agent/pi", "--ro-bind", str(tmp_path / "node/bin/node"),
                     "/opt/agent/node"]
    assert executable == "/opt/agent/pi/dist/bundle/cli.js"


class Tool:
    """A stand-in agent: a shell script, a login file, no model."""

    name = "tool"
    config_dir = ".tool"

    def __init__(self, script: Path):
        self.script = script

    def token_lifetime(self, real):
        return float("inf")

    def binds(self, real):
        return ["--ro-bind", str(self.script), "/opt/agent/tool"], "/opt/agent/tool"

    def seed(self, real, config, room):
        (config / "login").write_text("copy")

    def room_env(self, room):
        return {}


@pytest.mark.skipif(HOST != "darwin", reason="runs sandbox-exec")
def test_a_real_seatbelt_room_hides_the_home_and_keeps_the_runs_work(tmp_path, monkeypatch):
    script = tmp_path / "tool.sh"
    script.write_text('#!/bin/sh\nls "$REAL_HOME" >/dev/null 2>&1 && echo "home: listed" || echo "home: denied"\n'
                      'echo "cwd: $(pwd)"\necho made > made.txt\nrm gone.txt\necho tmp > "$TMPDIR/t" && echo "tmp: written"\n')
    script.chmod(0o755)
    work = project(tmp_path)
    real = Real(tmp_path, tmp_path, script)
    monkeypatch.setattr(sys, "platform", HOST)  # the fixture pinned linux; this test needs the real one
    with Seatbelt().open(Tool(script), real, work) as r:
        argv = Seatbelt().argv(r, Tool(script), real, ["tool"], {"REAL_HOME": str(Path.home())})
        proc = subprocess.run(argv, capture_output=True, text=True, timeout=60, cwd=Path.home())
        out = proc.stdout
        config = r.config(Tool(script))
        assert (config / "login").exists()
    assert "home: denied" in out and "tmp: written" in out
    assert f"cwd: {r.inside_work}" in out
    assert "getcwd" not in proc.stderr  # started from a directory the room cannot read
    assert (work / "made.txt").read_text() == "made\n" and not (work / "gone.txt").exists()
    assert not config.exists()


@pytest.mark.skipif(HOST != "darwin", reason="runs sandbox-exec")
def test_a_real_seatbelt_room_cannot_write_outside_the_room(tmp_path, monkeypatch):
    outside = next((p for p in ("/opt/homebrew", "/Applications", "/Library/Caches", "/usr/local")
                    if os.access(p, os.W_OK)), None)  # a place the user may write, outside the room
    if outside is None:
        pytest.skip("no place outside the room that this user may write, so a denied write would prove nothing")
    script = tmp_path / "tool.sh"
    script.write_text('#!/bin/sh\nf=$(mktemp "$OUTSIDE/.tare-test.XXXXXX" 2>/dev/null) && { rm -f "$f"; echo "outside: written"; }'
                      ' || echo "outside: denied"\n')
    script.chmod(0o755)
    real = Real(tmp_path, tmp_path, script)
    monkeypatch.setattr(sys, "platform", HOST)
    with Seatbelt().open(Tool(script), real, project(tmp_path)) as r:
        argv = Seatbelt().argv(r, Tool(script), real, ["tool"], {"OUTSIDE": outside})
        out = subprocess.run(argv, capture_output=True, text=True, timeout=60, cwd=Path.home()).stdout
    assert "outside: denied" in out


@pytest.mark.skipif(HOST != "darwin", reason="runs sandbox-exec")
def test_a_real_seatbelt_room_ends_what_the_agent_left_running(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(room, "_end_processes", REAL_END)  # the mac fixture's stub is not in this test
    script = tmp_path / "tool.sh"
    script.write_text('#!/bin/sh\nw=$(pwd)\nmkfifo "$TMPDIR/fifo"\n'
                      '(cd "$TMPDIR"; exec sleep 300) & echo $! > "$w/in-room.pid"\n'  # found by its working directory
                      '(cd /; exec /bin/sh -c "read x < $TMPDIR/fifo") & echo $! > "$w/names-room.pid"\n'  # by its command line
                      '(cd "$TMPDIR"; trap "" TERM; exec sleep 302) & echo $! > "$w/stubborn.pid"\n')  # needs SIGKILL
    script.chmod(0o755)
    real, work = Real(tmp_path, tmp_path, script), project(tmp_path)
    monkeypatch.setattr(sys, "platform", HOST)
    pids = []
    try:
        with Seatbelt().open(Tool(script), real, work) as r:
            subprocess.run(Seatbelt().argv(r, Tool(script), real, ["tool"]), timeout=60, cwd=Path.home())
            time.sleep(0.5)
            pids = [int((Path(r.inside_work) / f"{n}.pid").read_text()) for n in ("in-room", "names-room", "stubborn")]
            assert room._alive(pids) == pids
        assert room._alive(pids) == []
        assert "tare: ended 3 processes the agent left running in the room" in capsys.readouterr().err
    finally:
        for pid in pids:
            room._signal(pid, signal.SIGKILL)


def test_only_processes_that_name_the_room_or_work_in_it_are_its_own(monkeypatch, tmp_path):
    base = tmp_path / "tare-room-abc12345"
    base.mkdir()
    ps = (f" 101 /bin/sh -c read x < {base}/tmp/fifo\n"
          f" 102 {base}/opt/agent/claude -p hi\n"
          f" 103 tail -f {base}-copy/log\n"  # another directory whose name starts the same
          f" 104 vim /Users/me/tare-room-abc12345/notes\n"  # the same name elsewhere
          f" 105 vim /Users/me/tmp/tare-room-abc12345/notes\n 106 vim /var/tmp/tare-room-abc12345/notes\n"
          f" 107 /bin/sh -c cd \"{base}\"; sleep 300\n"  # the room itself, quoted
          f"   1 {base}/x\n   0 {base}/x\n garbage line {base}\n"
          f" {os.getpid()} python {base}/self\n")
    lsof = f"p201\nn{base}/tmp\np202\nn{base}\np203\nn/\npnotapid\nn{base}\np204\nn{base}-copy\n"
    monkeypatch.setattr(room, "_listing", lambda argv: ps if argv[0].endswith("ps") else lsof)
    assert room._room_processes(base) == [101, 102, 107, 201, 202]
    monkeypatch.setattr(room, "_listing", lambda argv: "")  # ps and lsof missing
    assert room._room_processes(base) == []


def test_a_signal_while_ending_processes_still_copies_back_removes_the_room_and_is_raised(tmp_path, monkeypatch, mac):
    real, _ = claude_on_mac(tmp_path, monkeypatch)
    work = project(tmp_path)

    def interrupted(base, grace=3.0):
        raise KeyboardInterrupt
    monkeypatch.setattr(room, "_end_processes", interrupted)
    with pytest.raises(KeyboardInterrupt):
        with Seatbelt().open(Claude(), real, work) as r:
            (Path(r.inside_work) / "made.txt").write_text("kept\n")
            base = r.home.parent
    assert (work / "made.txt").read_text() == "kept\n" and not base.exists()


def test_a_closed_stderr_does_not_stop_the_room_from_going(tmp_path, monkeypatch, mac):
    real, _ = claude_on_mac(tmp_path, monkeypatch)
    monkeypatch.setattr(room, "_end_processes", lambda base, grace=3.0: 2)

    class Gone:
        def write(self, text):
            raise BrokenPipeError

        def flush(self):
            raise BrokenPipeError
    with Seatbelt().open(Claude(), real, project(tmp_path)) as r:
        base = r.home.parent
        monkeypatch.setattr(sys, "stderr", Gone())
    assert not base.exists()


def test_a_failure_while_ending_processes_still_copies_back_and_removes_the_room(tmp_path, monkeypatch, mac, capsys):
    real, _ = claude_on_mac(tmp_path, monkeypatch)
    work = project(tmp_path)

    def broken(base, grace=3.0):
        raise ValueError("unparsable listing")
    monkeypatch.setattr(room, "_end_processes", broken)
    with Seatbelt().open(Claude(), real, work) as r:
        (Path(r.inside_work) / "made.txt").write_text("kept\n")
        base = r.home.parent
    assert (work / "made.txt").read_text() == "kept\n" and not base.exists()
    assert "could not end the processes left in the room: ValueError" in capsys.readouterr().err


def test_the_probe_looks_for_the_places_macos_keeps_and_for_the_pasteboard(tmp_path, monkeypatch, mac):
    real = Real(tmp_path, tmp_path / ".claude", tmp_path / "claude")
    argv = probe.reach(real)
    assert "pbpaste" in argv[2]
    for target in (tmp_path / "Library/Keychains", tmp_path / "Library/Preferences",
                   tmp_path / "Library/Application Support", "/private/var/folders/xy/user",
                   f"/private/tmp/claude-{os.getuid()}", "/private/var/tmp", "/Users/Shared"):
        assert str(target) in argv[4:]
    monkeypatch.setattr(sys, "platform", "linux")
    assert "pbpaste" not in probe.reach(real)[2] and "/Users/Shared" not in probe.reach(real)


def test_a_readable_pasteboard_in_the_room_is_a_leak(tmp_path):
    real = Real(tmp_path, tmp_path / ".claude", tmp_path / "claude")
    empty = agents.Capture("", set(), {})
    reading = probe.score(Claude(), real, empty, empty, "path pasteboard\n", "path pasteboard\n")
    assert [(f.kind, f.what) for f in reading.leaks] == [("reach", "pasteboard")]
    assert "reach" in reading.seen


def test_the_snapshot_hook_keeps_macos_metadata_out_of_capsules(tmp_path, monkeypatch):
    from tare.capsule import hook_script
    r = Room(tmp_path / "home", tmp_path / "w", tmp_path / "run")
    assert "\ntar -C /work -cf " in hook_script(r) and "COPYFILE_DISABLE" not in hook_script(r)
    monkeypatch.setattr(sys, "platform", "darwin")
    assert "\nCOPYFILE_DISABLE=1 tar -C /work -cf " in hook_script(r)


def test_the_judge_renders_on_macos_with_a_browser_of_its_own_in_a_seatbelt_room(tmp_path, monkeypatch, mac):
    from tare import judge
    monkeypatch.setattr(judge, "APPLICATIONS", tmp_path / "Applications")
    work = project(tmp_path)
    shot = tmp_path / "rooms" / "tare-render-x"
    shot.mkdir()
    with pytest.raises(RuntimeError, match="none is installed"):
        judge._render_on_macos(work, "index.html", shot, 2000)
    edge = tmp_path / "Applications" / judge.MAC_BROWSERS[2]
    edge.parent.mkdir(parents=True)
    edge.write_text("")
    argv = judge._render_on_macos(work, "index.html", shot, 2000)
    assert (shot / "work" / "src" / "keep.py").exists()  # the page is a clone in the room
    assert argv[argv.index("/usr/bin/sandbox-exec") + 3] == str(edge)
    assert f"MAC_CHROMIUM_TMPDIR={shot / 'tmp'}" in argv and "--use-mock-keychain" in argv
    assert f"--user-data-dir={shot / 'home' / 'browser'}" in argv and argv[-1] == f"file://{shot / 'work' / 'index.html'}"


def test_a_browser_that_keeps_running_after_its_screenshot_is_ended(tmp_path):
    from tare.judge import _run_until_shot
    png = tmp_path / "page.png"
    start = time.monotonic()
    _run_until_shot(["/bin/sh", "-c", f"echo png > {png}; sleep 60 & wait"], png, timeout=30)
    assert png.read_text() == "png\n" and time.monotonic() - start < 10


def test_claude_code_keeps_its_own_sandbox_off_in_a_macos_room(monkeypatch, mac):
    flags = Claude().room_flags
    assert flags[-2:] == ["--settings", '{"sandbox": {"enabled": false}}']
    # one --settings counts, the last: the hook's carries the sandbox switch too
    args = Claude().run_args("task", [], hook="/bin/sh /run/hook.sh")
    settings = json.loads(args[args.index("--settings") + 1])
    assert settings["sandbox"] == {"enabled": False} and settings["hooks"]["PostToolUse"]
    monkeypatch.setattr(sys, "platform", "linux")
    assert "--settings" not in Claude().room_flags
    assert "sandbox" not in Claude().run_args("task", [], hook="/bin/sh /run/hook.sh")[2]


def test_the_antigravity_cli_says_it_is_not_supported_on_macos(mac):
    with pytest.raises(TareError, match="not supported on macOS"):
        agents.AGENTS["agy"].discover()
