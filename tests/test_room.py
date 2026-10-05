import json
import os
import time

import pytest

from tare import room
from tare.room import Real, TareError, bwrap, room_home


def make_real(tmp_path, expires_in=7200):
    config = tmp_path / ".claude"
    config.mkdir()
    (config / ".credentials.json").write_text(json.dumps(
        {"claudeAiOauth": {"accessToken": "a", "refreshToken": "r", "expiresAt": (time.time() + expires_in) * 1000}}))
    return Real(home=tmp_path, config=config, state=tmp_path / ".claude.json", claude=tmp_path / "claude")


def test_room_home_holds_a_fresh_login_copy_and_is_removed(tmp_path):
    real = make_real(tmp_path)
    with room_home(real) as home:
        creds = home / ".claude-config" / ".credentials.json"
        assert creds.read_text() == (real.config / ".credentials.json").read_text()
        assert oct(creds.stat().st_mode & 0o777) == "0o600"
        state = json.loads((home / ".claude-config" / ".claude.json").read_text())
        assert state["projects"]["/work"]["hasTrustDialogAccepted"] is True
    assert not home.exists()


def test_room_refuses_a_login_that_would_need_a_refresh(tmp_path):
    real = make_real(tmp_path, expires_in=600)
    with pytest.raises(TareError, match="expires in"):
        with room_home(real):
            pass


def test_room_refuses_without_login(tmp_path):
    real = Real(home=tmp_path, config=tmp_path / ".claude", state=tmp_path / ".claude.json", claude=tmp_path / "c")
    with pytest.raises(TareError, match="log in first"):
        with room_home(real):
            pass


def test_bwrap_clears_the_environment_down_to_the_allowlist(tmp_path, monkeypatch):
    monkeypatch.setenv("SOME_API_KEY", "x")
    monkeypatch.setenv("TERM", "xterm")
    argv = bwrap(tmp_path, tmp_path, tmp_path / "claude", ["claude"], {"ANTHROPIC_BASE_URL": "http://f"})
    assert "--clearenv" in argv
    env = {argv[i + 1]: argv[i + 2] for i, a in enumerate(argv) if a == "--setenv"}
    assert "SOME_API_KEY" not in env
    assert env["TERM"] == "xterm" and env["HOME"] == room.ROOM_HOME
    assert env["ANTHROPIC_BASE_URL"] == "http://f" and env["ENABLE_TOOL_SEARCH"] == "true"
    assert argv[-2:] == ["--", "claude"]
    # nothing of the real home is mounted: /home is a tmpfs, only the room's own home sits on it
    assert any(argv[i:i + 2] == ["--tmpfs", "/home"] for i in range(len(argv)))
    targets = [argv[i + 2] for i, a in enumerate(argv) if a in ("--bind", "--ro-bind")]
    assert [t for t in targets if t.startswith("/home")] == [room.ROOM_HOME]


def test_real_reads_the_account_email(tmp_path):
    real = make_real(tmp_path)
    real.state.write_text(json.dumps({"oauthAccount": {"emailAddress": "me@example.org"}}))
    assert real.email() == "me@example.org"
    real.state.unlink()
    assert real.email() is None
