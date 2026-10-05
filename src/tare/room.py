"""The room: a bubblewrap sandbox where nothing of the user's came along.

Inside, /home is an empty tmpfs. Only a fresh per-run home (with a copy of the login),
the CLI binary and the project directory are mounted, and the environment is
cleared down to an allowlist. Linux and WSL only (bubblewrap, user namespaces).
"""
import json
import os
import shutil
import tempfile
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

ROOM_HOME = "/home/tare"
ROOM_CONFIG = f"{ROOM_HOME}/.claude-config"
ROOM_PROJECT = "/work"
AGENT_DIR = "/opt/agent"
CREDENTIALS = ".credentials.json"
# Copied from the caller when set; everything else stays outside.
PASS_ENV = ("TERM", "COLORTERM", "LANG", "LC_ALL")
# Login-carried connectors and account skills arrive unless these are passed (CONCEPT.md, layer 1).
ROOM_FLAGS = ["--strict-mcp-config", "--setting-sources", "project,local"]
# The room must not refresh the login: a refresh may rotate the token family the real
# session depends on (CONCEPT.md, layer 2). An hour covers ordinary runs.
MIN_TOKEN_LIFETIME = 3600


class TareError(Exception):
    pass


@dataclass(frozen=True)
class Real:
    """The user's real setup, outside the room."""

    home: Path
    config: Path  # the .claude directory
    state: Path  # .claude.json
    claude: Path  # resolved CLI binary

    @classmethod
    def discover(cls) -> "Real":
        home = Path.home()
        custom = os.environ.get("CLAUDE_CONFIG_DIR")
        config = Path(custom) if custom else home / ".claude"
        state = config / ".claude.json" if custom else home / ".claude.json"
        found = shutil.which("claude")
        if not found:
            raise TareError("claude is not on PATH")
        return cls(home, config, state, Path(found).resolve())

    def email(self) -> str | None:
        try:
            return json.loads(self.state.read_text())["oauthAccount"]["emailAddress"]
        except (OSError, ValueError, KeyError, TypeError):
            return None


def token_lifetime(real: Real) -> float:
    """Seconds until the login's access token expires. Never reads the token itself out."""
    path = real.config / CREDENTIALS
    try:
        expires_at = json.loads(path.read_text())["claudeAiOauth"]["expiresAt"]
    except (OSError, ValueError, KeyError, TypeError):
        raise TareError(f"no Claude login at {path}: run `claude` and log in first") from None
    return expires_at / 1000 - time.time()


@contextmanager
def room_home(real: Real):
    """A fresh home for one room, holding a copy of the login; removed afterwards."""
    left = token_lifetime(real)
    if left < MIN_TOKEN_LIFETIME:
        raise TareError(f"the login token expires in {max(0, int(left // 60))} min: "
                        "start any claude session to refresh it, then retry")
    home = Path(tempfile.mkdtemp(prefix="tare-room-"))
    try:
        config = home / ".claude-config"
        config.mkdir()
        shutil.copyfile(real.config / CREDENTIALS, config / CREDENTIALS)
        (config / CREDENTIALS).chmod(0o600)
        (config / ".claude.json").write_text(json.dumps(
            {"hasCompletedOnboarding": True, "projects": {ROOM_PROJECT: {"hasTrustDialogAccepted": True}}}))
        yield home
    finally:
        shutil.rmtree(home, ignore_errors=True)


def room_env(extra: dict[str, str]) -> dict[str, str]:
    env = {k: os.environ[k] for k in PASS_ENV if k in os.environ}
    env |= {"HOME": ROOM_HOME, "CLAUDE_CONFIG_DIR": ROOM_CONFIG, "PATH": f"{AGENT_DIR}:/usr/bin:/bin",
            # A custom base URL turns tool search off; keep probe and run in the same form.
            "ENABLE_TOOL_SEARCH": "true"}
    return env | extra


def bwrap(home: Path, project: Path, claude: Path, command: list[str], extra_env: dict[str, str] | None = None) -> list[str]:
    argv = ["bwrap", "--ro-bind", "/usr", "/usr", "--ro-bind", "/etc", "/etc",
            "--symlink", "usr/bin", "/bin", "--symlink", "usr/lib", "/lib", "--symlink", "usr/lib64", "/lib64"]
    if Path("/mnt/wsl").is_dir():
        # WSL keeps the resolver behind a symlink into /mnt/wsl; without it DNS fails.
        argv += ["--ro-bind", "/mnt/wsl", "/mnt/wsl"]
    argv += ["--proc", "/proc", "--dev", "/dev", "--tmpfs", "/tmp", "--tmpfs", "/home",
             "--bind", str(home), ROOM_HOME,
             "--ro-bind", str(claude), f"{AGENT_DIR}/claude",
             "--bind", str(project), ROOM_PROJECT, "--chdir", ROOM_PROJECT,
             "--unshare-user", "--unshare-pid", "--unshare-ipc", "--unshare-uts", "--die-with-parent",
             "--clearenv"]
    for key, value in room_env(extra_env or {}).items():
        argv += ["--setenv", key, value]
    return argv + ["--", *command]
