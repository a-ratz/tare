import base64
import json
import time
from pathlib import Path

import pytest

from tare import room
from tare.agents import Claude, Codex, Real
from tare.room import TareError, bwrap, room_home


def claude_real(tmp_path, expires_in=7200):
    config = tmp_path / ".claude"
    config.mkdir()
    (config / ".credentials.json").write_text(json.dumps(
        {"claudeAiOauth": {"accessToken": "a", "refreshToken": "r", "expiresAt": (time.time() + expires_in) * 1000}}))
    return Real(home=tmp_path, config=config, binary=tmp_path / "claude")


def jwt(claims):
    payload = base64.urlsafe_b64encode(json.dumps(claims).encode()).decode().rstrip("=")
    return f"header.{payload}.signature"


def codex_real(tmp_path, expires_in=7200, binary=Path("/usr/lib/node_modules/@openai/codex/bin/codex.js")):
    config = tmp_path / ".codex"
    config.mkdir()
    (config / "auth.json").write_text(json.dumps(
        {"OPENAI_API_KEY": None, "tokens": {"access_token": jwt({"exp": time.time() + expires_in}), "refresh_token": "r"}}))
    return Real(home=tmp_path, config=config, binary=binary)


def test_claude_room_home_holds_a_fresh_login_copy_and_is_removed(tmp_path):
    real = claude_real(tmp_path)
    with room_home(Claude(), real) as home:
        creds = home / ".claude-config" / ".credentials.json"
        assert creds.read_text() == (real.config / ".credentials.json").read_text()
        assert oct(creds.stat().st_mode & 0o777) == "0o600"
        state = json.loads((home / ".claude-config" / ".claude.json").read_text())
        assert state["projects"]["/work"]["hasTrustDialogAccepted"] is True
    assert not home.exists()


def test_codex_room_home_holds_a_login_copy_and_trusts_the_project(tmp_path):
    real = codex_real(tmp_path)
    with room_home(Codex(), real) as home:
        auth = home / ".codex" / "auth.json"
        assert auth.read_text() == (real.config / "auth.json").read_text()
        assert oct(auth.stat().st_mode & 0o777) == "0o600"
        assert '[projects."/work"]' in (home / ".codex" / "config.toml").read_text()
    assert not home.exists()


@pytest.mark.parametrize("make, agent", [(claude_real, Claude()), (codex_real, Codex())])
def test_room_refuses_a_login_that_would_need_a_refresh(tmp_path, make, agent):
    real = make(tmp_path, expires_in=600)
    with pytest.raises(TareError, match="expires in"):
        with room_home(agent, real):
            pass


def test_codex_api_key_login_never_expires(tmp_path):
    real = codex_real(tmp_path)
    (real.config / "auth.json").write_text(json.dumps({"OPENAI_API_KEY": "sk-test"}))
    assert Codex().token_lifetime(real) == float("inf")


@pytest.mark.parametrize("agent", [Claude(), Codex()])
def test_room_refuses_without_login(tmp_path, agent):
    real = Real(home=tmp_path, config=tmp_path / "missing", binary=Path("/usr/bin/x"))
    with pytest.raises(TareError, match="log in"):
        with room_home(agent, real):
            pass


def test_bwrap_clears_the_environment_down_to_the_allowlist(tmp_path, monkeypatch):
    monkeypatch.setenv("SOME_API_KEY", "x")
    monkeypatch.setenv("TERM", "xterm")
    real = claude_real(tmp_path)
    argv = bwrap(Claude(), real, tmp_path, tmp_path, ["claude", "-p"], {"ANTHROPIC_BASE_URL": "http://f"})
    assert "--clearenv" in argv
    env = {argv[i + 1]: argv[i + 2] for i, a in enumerate(argv) if a == "--setenv"}
    assert "SOME_API_KEY" not in env
    assert env["TERM"] == "xterm" and env["HOME"] == room.ROOM_HOME
    assert env["ANTHROPIC_BASE_URL"] == "http://f" and env["ENABLE_TOOL_SEARCH"] == "true"
    assert argv[-3:] == ["--", "/opt/agent/claude", "-p"]
    # nothing of the real home is mounted: /home is a tmpfs, only the room's own home sits on it
    assert any(argv[i:i + 2] == ["--tmpfs", "/home"] for i in range(len(argv)))
    targets = [argv[i + 2] for i, a in enumerate(argv) if a in ("--bind", "--ro-bind")]
    assert [t for t in targets if t.startswith("/home")] == [room.ROOM_HOME]


def test_bwrap_for_codex_points_codex_home_into_the_room(tmp_path):
    argv = bwrap(Codex(), codex_real(tmp_path), tmp_path, tmp_path, ["codex", "exec"])
    env = {argv[i + 1]: argv[i + 2] for i, a in enumerate(argv) if a == "--setenv"}
    assert env["CODEX_HOME"] == "/home/tare/.codex"
    assert argv[-3:] == ["--", "codex", "exec"]


def test_codex_outside_usr_is_refused(tmp_path):
    with pytest.raises(TareError, match="under /usr"):
        bwrap(Codex(), codex_real(tmp_path, binary=tmp_path / "codex"), tmp_path, tmp_path, ["codex"])


def test_claude_reads_the_account_email(tmp_path, monkeypatch):
    monkeypatch.delenv("CLAUDE_CONFIG_DIR", raising=False)
    real = claude_real(tmp_path)
    (tmp_path / ".claude.json").write_text(json.dumps({"oauthAccount": {"emailAddress": "me@example.org"}}))
    assert Claude().email(real) == "me@example.org"
    (tmp_path / ".claude.json").unlink()
    assert Claude().email(real) is None


def test_adapters_take_every_path_from_the_room_so_a_backend_without_mounts_can_use_host_paths(tmp_path):
    from tare.agents import Pi
    from tare.room import Room, room_env
    room = Room(tmp_path / "home", tmp_path / "work", None, "/private/tmp/r1/home", "/private/tmp/r1/work", "/private/tmp/r1/run")
    assert room_env(Claude(), room)["CLAUDE_CONFIG_DIR"] == "/private/tmp/r1/home/.claude-config"
    assert room_env(Codex(), room)["CODEX_HOME"] == "/private/tmp/r1/home/.codex"
    assert room_env(Pi(), room)["HOME"] == "/private/tmp/r1/home"
    Claude().place_session(room, "s1", ["{}"])
    assert (tmp_path / "home" / ".claude-config" / "projects" / "-private-tmp-r1-work" / "s1.jsonl").exists()
    Pi().place_session(room, "s2", ["{}"])
    assert (tmp_path / "home" / ".pi" / "agent" / "sessions" / "--private-tmp-r1-work--").is_dir()
    config = tmp_path / "codex-config"
    config.mkdir()
    Codex().seed(codex_real(tmp_path), config, room)
    assert '[projects."/private/tmp/r1/work"]' in (config / "config.toml").read_text()
    assert "-e" in Pi().run_args("t", [], hook="h", room=room) and \
        "/private/tmp/r1/home/.pi/agent/tare-snapshot.ts" in Pi().run_args("t", [], hook="h", room=room)
