"""The room: a bubblewrap sandbox where nothing of the user's came along.

Inside, /home is an empty tmpfs. Only a fresh per-run home (with a copy of the agent's
login), the CLI and the project directory are mounted, and the environment is cleared
down to an allowlist. Linux and WSL only (bubblewrap, user namespaces).
"""
import os
import shutil
import tempfile
from contextlib import contextmanager
from pathlib import Path

ROOM_HOME = "/home/tare"
ROOM_PROJECT = "/work"
# Copied from the caller when set; everything else stays outside.
PASS_ENV = ("TERM", "COLORTERM", "LANG", "LC_ALL")
# The room must not refresh the login: a refresh may rotate the token family the real
# session depends on (CONCEPT.md, layer 2). An hour covers ordinary runs.
MIN_TOKEN_LIFETIME = 3600


class TareError(Exception):
    pass


@contextmanager
def room_home(agent, real):
    """A fresh home for one room, holding a copy of the agent's login; removed afterwards."""
    left = agent.token_lifetime(real)
    if left < MIN_TOKEN_LIFETIME:
        raise TareError(f"the {agent.name} login token expires in {max(0, int(left // 60))} min: "
                        f"start any {agent.name} session to refresh it, then retry")
    home = Path(tempfile.mkdtemp(prefix="tare-room-"))
    try:
        config = home / Path(agent.room_config).relative_to(ROOM_HOME)
        config.mkdir(parents=True)
        agent.seed(real, config)
        yield home
    finally:
        shutil.rmtree(home, ignore_errors=True)


def room_env(agent, extra: dict[str, str] | None = None) -> dict[str, str]:
    env = {k: os.environ[k] for k in PASS_ENV if k in os.environ}
    env |= {"HOME": ROOM_HOME, "PATH": "/opt/agent:/usr/bin:/bin", **agent.room_env()}
    return env | (extra or {})


def bwrap(agent, real, home: Path, project: Path, command: list[str], extra_env: dict[str, str] | None = None,
          extra_binds: list[str] | None = None) -> list[str]:
    """The bwrap command for one room. `command[0]` may be the agent's own name."""
    binds, executable = agent.binds(real)
    if command and command[0] == agent.name:
        command = [executable, *command[1:]]
    argv = ["bwrap", "--ro-bind", "/usr", "/usr", "--ro-bind", "/etc", "/etc",
            "--symlink", "usr/bin", "/bin", "--symlink", "usr/lib", "/lib", "--symlink", "usr/lib64", "/lib64"]
    if Path("/mnt/wsl").is_dir():
        # WSL keeps the resolver behind a symlink into /mnt/wsl; without it DNS fails.
        argv += ["--ro-bind", "/mnt/wsl", "/mnt/wsl"]
    argv += ["--proc", "/proc", "--dev", "/dev", "--tmpfs", "/tmp", "--tmpfs", "/home",
             "--bind", str(home), ROOM_HOME, *binds, *(extra_binds or []),
             "--bind", str(project), ROOM_PROJECT, "--chdir", ROOM_PROJECT,
             "--unshare-user", "--unshare-pid", "--unshare-ipc", "--unshare-uts", "--die-with-parent",
             "--clearenv"]
    for key, value in room_env(agent, extra_env).items():
        argv += ["--setenv", key, value]
    return argv + ["--", *command]
