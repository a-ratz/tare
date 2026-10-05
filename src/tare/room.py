"""The room: an isolated environment where nothing of the user's came along.

A backend builds the room. On Linux and WSL that is bubblewrap: inside, /home is an empty
tmpfs, and only a fresh per-run home (with a copy of the agent's login), the CLI and the
project directory are mounted, at fixed paths. The environment is cleared down to an
allowlist. On macOS it is Seatbelt, which cannot mount: the room is one directory holding the
home and clones of the project and the CLI, at host paths. So every path the agent sees comes
from the `Room` its backend built, never from a constant.
"""
import functools
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path

# where bubblewrap mounts the room's home, the project and a run's store
ROOM_HOME = "/home/tare"
ROOM_PROJECT = "/work"
ROOM_RUN = "/tare-run"
# where Seatbelt rooms live: the profile denies the rest of /private/tmp
SEATBELT_ROOMS = "/private/tmp"
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
    env: dict[str, str] = field(default_factory=dict, compare=False)  # the backend's own variables (PATH, TMPDIR)

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
    env |= {"HOME": room.inside_home, "PATH": "/opt/agent:/usr/bin:/bin", **room.env, **agent.room_env(room)}
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


class Seatbelt:
    """macOS: a Seatbelt profile (sandbox-exec). The room is one directory under /private/tmp:
    the home, the project cloned to `work`, and the CLI cloned to where bubblewrap would mount
    it (`opt/agent/...`). APFS clones are copy-on-write, so they cost next to nothing. The
    profile denies the user's home and the places where the user's other programs keep their
    files (measured in #86). The run's changes to the clone go back to the project on close."""

    @contextmanager
    def open(self, agent, real, work: Path, run: Path | None = None):
        _check_login(agent, real)
        base = Path(tempfile.mkdtemp(prefix="tare-room-", dir=SEATBELT_ROOMS))
        clone, before = base / "work", None
        try:
            for source, inside in _mounts(agent.binds(real)[0]):
                _clone(Path(source), base / inside.lstrip("/"))
            _clone(work, clone)
            before = _state(clone)
            (base / "tmp").mkdir()
            room = Room(base / "home", work, run, str(base / "home"), str(clone), str(run) if run else ROOM_RUN,
                        {"PATH": f"{base}/opt/agent:/usr/bin:/bin", "TMPDIR": str(base / "tmp")})
            room.config(agent).mkdir(parents=True)
            agent.seed(real, room.config(agent), room)
            yield room
        finally:
            if before is not None:
                _copy_back(before, clone, work)
            shutil.rmtree(base, ignore_errors=True)

    def argv(self, room: Room, agent, real, command: list[str], extra_env: dict[str, str] | None = None) -> list[str]:
        """The command line that runs `command` in the room. `command[0]` may be the agent's own name."""
        _, executable = agent.binds(real)
        if command and command[0] == agent.name:
            inside = f"{room.home.parent}{executable}" if executable.startswith("/") else executable
            command = [inside, *command[1:]]
        env = [f"{k}={v}" for k, v in room_env(agent, room, extra_env).items()]
        # sandbox-exec keeps the caller's environment and working directory: clear the one, set the other
        return ["/usr/bin/env", "-i", *env, "/usr/bin/sandbox-exec", "-p", profile(room),
                "/bin/sh", "-c", 'cd "$0" && exec "$@"', room.inside_work, *command]


@functools.cache
def _user_dir() -> Path:
    """The user's directory under /var/folders: its T and C hold other programs' temporary files and caches."""
    out = subprocess.run(["getconf", "DARWIN_USER_DIR"], capture_output=True, text=True, check=True).stdout
    return Path(out.strip()).resolve().parent


def profile(room: Room) -> str:
    """The Seatbelt profile of a room. The last matching rule wins, so it denies broadly, then allows the room."""
    base = room.home.parent

    def q(path) -> str:  # an SBPL string
        return json.dumps(str(path), ensure_ascii=False)

    denied = (Path.home().resolve(), _user_dir(), "/private/tmp", "/private/var/tmp", "/Users/Shared")
    rules = ["(version 1)", "(allow default)",
             f"(deny file-read* file-write* {' '.join(f'(subpath {q(p)})' for p in denied)})",
             # the pasteboard holds whatever the user copied last
             '(deny mach-lookup (global-name "com.apple.pasteboard.1"))',
             f"(allow file-read* file-write* (subpath {q(base)}))",
             f"(deny file-write* (subpath {q(base / 'opt')}))",
             # realpath() of anything in the room lstat()s /private/tmp
             '(allow file-read-metadata (literal "/private/tmp"))']
    if room.run:
        rules.append(f"(allow file-read* file-write* (subpath {q(room.run)}))")
    return "\n".join(rules) + "\n"


def _mounts(binds: list[str]) -> list[tuple[str, str]]:
    """The (host, inside) pairs of an adapter's bwrap binds (`--ro-bind host inside`)."""
    return [(binds[i + 1], binds[i + 2]) for i in range(0, len(binds), 3)]


def _clone(source: Path, target: Path):
    """An APFS clone of a file or a tree; a plain copy where the volume cannot clone."""
    target.parent.mkdir(parents=True, exist_ok=True)
    if subprocess.run(["cp", "-c", "-R", "-p", str(source), str(target)], capture_output=True).returncode:
        if target.is_dir() and not target.is_symlink():
            shutil.rmtree(target)
        else:
            target.unlink(missing_ok=True)
        subprocess.run(["cp", "-R", "-p", str(source), str(target)], capture_output=True, check=True)


def _state(root: Path) -> dict[str, tuple]:
    """Every entry under `root`, by relative path: its kind and what a change would alter."""
    state = {}
    for directory, dirs, files in os.walk(root):
        for name in dirs + files:
            path = Path(directory, name)
            st = path.lstat()
            if stat.S_ISLNK(st.st_mode):
                state[str(path.relative_to(root))] = ("link", os.readlink(path))
            elif stat.S_ISDIR(st.st_mode):
                state[str(path.relative_to(root))] = ("dir", st.st_mode)
            else:
                state[str(path.relative_to(root))] = ("file", st.st_mode, st.st_size, st.st_mtime_ns)
    return state


def _remove(path: Path):
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path)
    else:
        path.unlink(missing_ok=True)


def _copy_back(before: dict[str, tuple], clone: Path, work: Path):
    """Apply what the run changed in the clone to `work`: new and changed entries are copied over,
    removed ones are removed. An entry the run did not touch stays as it is in `work`, even if
    the user changed it meanwhile."""
    after = _state(clone)
    for rel in sorted(before.keys() - after.keys(), reverse=True):  # a directory's entries before the directory
        _remove(work / rel)
    for rel in sorted(after):  # a directory before its entries
        if before.get(rel) == after[rel]:
            continue
        source, target = clone / rel, work / rel
        if after[rel][0] == "dir":
            if not target.is_dir() or target.is_symlink():
                _remove(target)
                target.mkdir()
            target.chmod(stat.S_IMODE(after[rel][1]))
            continue
        _remove(target)
        if after[rel][0] == "link":
            target.symlink_to(os.readlink(source))
        else:
            shutil.copy2(source, target)


def backend():
    """The room backend for this platform."""
    return Seatbelt() if sys.platform == "darwin" else Bubblewrap()


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
