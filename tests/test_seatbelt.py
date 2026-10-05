import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from conftest import HOST
from tare import agents, probe, room
from tare.agents import Claude, Codex, Pi, Real
from tare.room import Room, Seatbelt, TareError


@pytest.fixture
def mac(monkeypatch, tmp_path):
    """macOS as Seatbelt sees it, with the rooms under tmp_path."""
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(room, "SEATBELT_ROOMS", str(tmp_path / "rooms"))
    monkeypatch.setattr(room, "_user_dir", lambda: Path("/private/var/folders/xy/user"))
    monkeypatch.setattr(probe, "_user_dir", room._user_dir)
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


def test_seatbelt_argv_clears_the_environment_and_runs_the_clone_in_the_work_clone(tmp_path, monkeypatch, mac):
    real, _ = claude_on_mac(tmp_path, monkeypatch)
    with Seatbelt().open(Claude(), real, project(tmp_path)) as r:
        base = r.home.parent
        argv = Seatbelt().argv(r, Claude(), real, ["claude", "-p", "hi"], {"ANTHROPIC_BASE_URL": "http://fake"})
    assert argv[:2] == ["/usr/bin/env", "-i"]
    env = dict(a.split("=", 1) for a in argv[2:argv.index("/usr/bin/sandbox-exec")])
    assert env["HOME"] == str(base / "home")
    assert env["PATH"] == f"{base}/opt/agent:/usr/bin:/bin"
    assert env["TMPDIR"] == env["CLAUDE_CODE_TMPDIR"] == str(base / "tmp")
    assert env["CLAUDE_CONFIG_DIR"] == str(base / "home/.claude-config")
    assert env["ANTHROPIC_BASE_URL"] == "http://fake"
    assert argv[-5:] == ['cd "$0" && exec "$@"', str(base / "work"), f"{base}/opt/agent/claude", "-p", "hi"]


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
                      'echo "cwd: $PWD"\necho made > made.txt\nrm gone.txt\n')
    script.chmod(0o755)
    work = project(tmp_path)
    real = Real(tmp_path, tmp_path, script)
    monkeypatch.setattr(sys, "platform", HOST)  # the fixture pinned linux; this test needs the real one
    with Seatbelt().open(Tool(script), real, work) as r:
        argv = Seatbelt().argv(r, Tool(script), real, ["tool"], {"REAL_HOME": str(Path.home())})
        out = subprocess.run(argv, capture_output=True, text=True, timeout=60).stdout
        config = r.config(Tool(script))
        assert (config / "login").exists()
    assert "home: denied" in out
    assert f"cwd: {r.inside_work}" in out
    assert (work / "made.txt").read_text() == "made\n" and not (work / "gone.txt").exists()
    assert not config.exists()


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
