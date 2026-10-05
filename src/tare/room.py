"""The room: an isolated environment where nothing of the user's came along.

A backend builds the room. On Linux and WSL that is bubblewrap: inside, /home is an empty
tmpfs, and only a fresh per-run home (with a copy of the agent's login), the CLI and the
project directory are mounted, at fixed paths. The environment is cleared down to an
allowlist. A backend that cannot mount (Seatbelt on macOS, epic #85) keeps the host paths, so
every path the agent sees comes from the `Room` it built, never from a constant.
"""
import os
import shutil
import sys
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

# where bubblewrap mounts the room's home, the project and a run's store
ROOM_HOME = "/home/tare"
ROOM_PROJECT = "/work"
ROOM_RUN = "/tare-run"
# Copied from the caller when set; everything else stays outside.
PASS_ENV = ("TERM", "COLORTERM", "LANG", "LC_ALL")
# The room must not refresh the login: a refresh may rotate the token family the real
# session depends on (CONCEPT.md, layer 2). An hour covers ordinary runs.
MIN_TOKEN_LIFETIME = 3600


class TareError(Exception):
    pass


@dataclass(frozen=True)
class Room:
    """A room as its backend built it: host paths for tare, and the paths the agent sees inside.

    `home`, `work` and `run` are on the host. `work` is the project the agent works on, and its
    changes must be in `work` once the room closes. `run` is a run's store (capsules and the
    snapshot hook), when there is one. The inside paths are what the agent and its hooks see."""

    home: Path
    work: Path
    run: Path | None = None
    inside_home: str = ROOM_HOME
    inside_work: str = ROOM_PROJECT
    inside_run: str = ROOM_RUN

    def config(self, agent) -> Path:
        """The agent's config directory in the room, on the host."""
        return self.home / agent.config_dir

    def inside_config(self, agent) -> str:
        """The agent's config directory as the agent sees it."""
        return f"{self.inside_home}/{agent.config_dir}"


def _check_login(agent, real):
    left = agent.token_lifetime(real)
    if left < MIN_TOKEN_LIFETIME:
        raise TareError(f"the {agent.name} login token expires in {max(0, int(left // 60))} min: "
                        f"start any {agent.name} session to refresh it, then retry")


def room_env(agent, room: Room | None = None, extra: dict[str, str] | None = None) -> dict[str, str]:
    """The room's whole environment: the allowlist, the room's own HOME and PATH, the agent's variables."""
    room = room or Room(Path(), Path())
    env = {k: os.environ[k] for k in PASS_ENV if k in os.environ}
    env |= {"HOME": room.inside_home, "PATH": "/opt/agent:/usr/bin:/bin", **agent.room_env(room)}
    return env | (extra or {})


class Bubblewrap:
    """Linux and WSL: user namespaces, an empty /home, the room mounted at fixed inside paths."""

    @contextmanager
    def open(self, agent, real, work: Path, run: Path | None = None):
        """A fresh room for one run, holding a copy of the agent's login; removed afterwards.
        `work` is mounted, so the agent's changes land there directly."""
        _check_login(agent, real)
        home = Path(tempfile.mkdtemp(prefix="tare-room-"))
        try:
            room = Room(home, work, run)
            room.config(agent).mkdir(parents=True)
            agent.seed(real, room.config(agent), room)
            yield room
        finally:
            shutil.rmtree(home, ignore_errors=True)

    def argv(self, room: Room, agent, real, command: list[str], extra_env: dict[str, str] | None = None,
             extra_binds: list[str] | None = None) -> list[str]:
        """The command line that runs `command` in the room. `command[0]` may be the agent's own name."""
        binds, executable = agent.binds(real)
        if command and command[0] == agent.name:
            command = [executable, *command[1:]]
        argv = ["bwrap", "--ro-bind", "/usr", "/usr", "--ro-bind", "/etc", "/etc",
                "--symlink", "usr/bin", "/bin", "--symlink", "usr/lib", "/lib", "--symlink", "usr/lib64", "/lib64"]
        if Path("/mnt/wsl").is_dir():
            # WSL keeps the resolver behind a symlink into /mnt/wsl; without it DNS fails.
            argv += ["--ro-bind", "/mnt/wsl", "/mnt/wsl"]
        run = ["--bind", str(room.run), room.inside_run] if room.run else []
        argv += ["--proc", "/proc", "--dev", "/dev", "--tmpfs", "/tmp", "--tmpfs", "/home",
                 "--bind", str(room.home), room.inside_home, *binds, *run, *(extra_binds or []),
                 "--bind", str(room.work), room.inside_work, "--chdir", room.inside_work,
                 "--unshare-user", "--unshare-pid", "--unshare-ipc", "--unshare-uts", "--die-with-parent",
                 "--clearenv"]
        for key, value in room_env(agent, room, extra_env).items():
            argv += ["--setenv", key, value]
        return argv + ["--", *command]


def backend():
    """The room backend for this platform."""
    if sys.platform == "darwin":
        raise TareError("rooms on macOS are not built yet (epic #85)")
    return Bubblewrap()


# Linux helpers in the old shape, kept for the experiment scripts that recorded measurements with them.

@contextmanager
def room_home(agent, real):
    """A fresh bubblewrap room home; yields its host path."""
    with Bubblewrap().open(agent, real, Path(ROOM_PROJECT)) as room:
        yield room.home


def bwrap(agent, real, home: Path, project: Path, command: list[str], extra_env: dict[str, str] | None = None,
          extra_binds: list[str] | None = None) -> list[str]:
    """The bwrap command for a room home from `room_home` and a project."""
    return Bubblewrap().argv(Room(home, project), agent, real, command, extra_env, extra_binds)
