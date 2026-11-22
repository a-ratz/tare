"""The room: an isolated environment where nothing of the user's came along.

A backend builds the room. On Linux and WSL that is bubblewrap: inside, /home is an empty
tmpfs, and only a fresh per-run home (with a copy of the agent's login), the CLI and the
project directory are mounted, at fixed paths. The environment is cleared down to an
allowlist. On macOS it is Seatbelt, which cannot mount: the room is one directory holding the
home and clones of the project and the CLI, at host paths. So every path the agent sees comes
from the `Room` its backend built, never from a constant.
"""
import fcntl
import functools
import json
import os
import re
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import time
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
# session depends on (CONCEPT.md, layer 2). An hour covers ordinary runs; a shorter run may
# ask for less, but never so little that the copy starts close to its renewal.
MIN_TOKEN_LIFETIME = 3600
MIN_LOGIN_ENV = "TARE_MIN_LOGIN_MINUTES"
MIN_LOGIN_FLOOR = 10  # minutes


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


def _min_lifetime() -> int:
    """Seconds the login copy must still hold: an hour, or what TARE_MIN_LOGIN_MINUTES asks for."""
    minutes = os.environ.get(MIN_LOGIN_ENV)
    if minutes is None:
        return MIN_TOKEN_LIFETIME
    if not minutes.isdigit() or int(minutes) < MIN_LOGIN_FLOOR:
        raise TareError(f"{MIN_LOGIN_ENV} must be a whole number of minutes, at least {MIN_LOGIN_FLOOR}")
    return int(minutes) * 60


def _check_login(agent, real):
    left = agent.token_lifetime(real)
    if left < _min_lifetime():
        # the agent renews only close to expiry, so a session started earlier changes nothing
        # with the zone: on the night the clocks go back, a bare 02:04 reads as already past
        minutes, at = max(0, int(left // 60)), time.strftime("%H:%M %Z", time.localtime(time.time() + left)).strip()
        shorter = (f"; a run that ends well before then can start now with {MIN_LOGIN_ENV}={minutes} or less"
                   if minutes >= MIN_LOGIN_FLOOR else "")
        raise TareError(f"the {agent.name} login token expires in {minutes} min, at {at}: to renew it, start "
                        f"{agent.name} outside tare after {at}, then retry{shorter}")


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
        lock = _hold(home)
        try:
            room = Room(home, work, run)
            room.config(agent).mkdir(parents=True)
            agent.seed(real, room.config(agent), room)
            yield room
        finally:
            _rmtree(home)
            _release(lock, home)

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
        argv += _resolver()
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
        lock = _hold(base)
        clone, before = base / "work", None
        try:
            for source, inside in _mounts(agent.binds(real)[0]):
                _clone(Path(source), base / inside.lstrip("/"))
            _clone(work, clone)
            before = _state(clone)
            (base / "tmp").mkdir()
            path, tmp = ":".join([f"{base}/opt/agent", *_developer_bin(), "/usr/bin", "/bin"]), str(base / "tmp")
            room = Room(base / "home", work, run, str(base / "home"), str(clone), str(run) if run else ROOM_RUN,
                        {"PATH": path, "TMPDIR": tmp, **_browser_env(tmp)})
            room.config(agent).mkdir(parents=True)
            agent.seed(real, room.config(agent), room)
            yield room
        finally:
            # ending the room's processes must never stop the copy-back or the room's removal: a signal
            # that arrives meanwhile (Ctrl-C, SIGTERM, SIGHUP) is raised again once the room is gone
            interrupted = None
            try:
                ended = _end_processes(base)
                if ended:
                    _say(f"tare: ended {ended} process{'es' if ended != 1 else ''} the agent left running in the room")
            except Exception as e:
                _say(f"tare: could not end the processes left in the room: {type(e).__name__}: {e}")
            except BaseException as e:
                interrupted = e
            copied = False
            try:
                if before is not None:
                    _copy_back(before, clone, work)
                copied = True
            finally:
                if copied:
                    _rmtree(base)
                    _release(lock, base)
                else:  # the run's changes are only in the clone: keep it, remove the rest, the login copy too (#187)
                    for part in base.iterdir() if base.is_dir() else []:
                        if part != clone:
                            _rmtree(part)
                    _say(f"tare: could not copy the run's changes back to {work}; they are in {clone}")
                    _release(lock, base, kept=True)
            if interrupted is not None:
                raise interrupted

    def argv(self, room: Room, agent, real, command: list[str], extra_env: dict[str, str] | None = None) -> list[str]:
        """The command line that runs `command` in the room. `command[0]` may be the agent's own name."""
        _, executable = agent.binds(real)
        if command and command[0] == agent.name:
            inside = f"{room.home.parent}{executable}" if executable.startswith("/") else executable
            command = [inside, *command[1:]]
        env = [f"{k}={v}" for k, v in room_env(agent, room, extra_env).items()]
        # sandbox-exec keeps the caller's working directory and environment: enter the room's work
        # directory first (from inside, the caller's may be unreadable), then clear the environment
        return ["/bin/sh", "-c", 'cd "$0" && exec "$@"', room.inside_work,
                "/usr/bin/env", "-i", *env, "/usr/bin/sandbox-exec", "-p", profile(room), *command]


@functools.cache
def _resolver(conf: Path = Path("/etc/resolv.conf")) -> list[str]:
    """The bind for a resolver file that sits outside the room's mounts.

    systemd-resolved, NetworkManager and resolvconf keep /etc/resolv.conf as a symlink into /run. The room
    mounts /etc but not /run, so the link would point nowhere and no host name would resolve. Only the file
    the link names is mounted, not its directory.
    """
    target = conf.resolve()
    if not conf.is_symlink() or not target.is_file() or str(target).startswith(("/etc/", "/usr/", "/mnt/wsl/")):
        return []
    return ["--ro-bind", str(target), str(target)]


def _user_dir() -> Path:
    """The user's directory under /var/folders: its T and C hold other programs' temporary files and caches."""
    out = subprocess.run(["getconf", "DARWIN_USER_DIR"], capture_output=True, text=True, check=True).stdout
    return Path(out.strip()).resolve().parent


def _browser_env(tmp: str) -> dict[str, str]:
    """What a Chromium browser needs in a Seatbelt room. It takes the user's temporary directory, which
    the profile denies, unless MAC_CHROMIUM_TMPDIR names another (it ignores TMPDIR). Its own sandbox
    cannot start inside the room's, as no Seatbelt profile can, so agent-browser gets --no-sandbox
    (Playwright passes it anyway)."""
    return {"MAC_CHROMIUM_TMPDIR": tmp, "AGENT_BROWSER_ARGS": "--no-sandbox"}


def _developer_bin() -> list[str]:
    """The active developer directory's usr/bin, where git, python3 and make run as themselves. Those in
    /usr/bin are shims that ask xcrun, whose cache lives in the user's temporary directory: in a room
    each call would print that it cannot write the cache. The system's choice only (`xcode-select -s`,
    not the caller's DEVELOPER_DIR), and never a place the room denies, such as the home."""
    try:
        found = subprocess.run(["/usr/bin/xcode-select", "-p"], capture_output=True, text=True, timeout=10, env={})
    except (OSError, subprocess.SubprocessError):
        return []
    tools = Path(found.stdout.strip(), "usr", "bin")
    if found.returncode or not tools.is_absolute() or not tools.is_dir():
        return []
    resolved = tools.resolve()  # what Seatbelt matches, and no detour through a denied place on PATH
    return [] if any(resolved.is_relative_to(Path(d).resolve()) for d in _denied()) else [str(resolved)]


def _denied() -> tuple:
    """Where a Seatbelt room may neither read nor write: the home, the user's directory under
    /var/folders, and the places other programs share."""
    return (Path.home().resolve(), _user_dir(), "/private/tmp", "/private/var/tmp", "/Users/Shared")


def profile(room: Room) -> str:
    """The Seatbelt profile of a room. The last matching rule wins, so it denies broadly, then allows the room.
    Reading stays open outside the denied places; writing does not (devices aside)."""
    base = room.home.parent

    def q(path) -> str:  # an SBPL string
        return json.dumps(str(path), ensure_ascii=False)

    denied = _denied()
    rules = ["(version 1)", "(allow default)",
             # writes stay in the room, as in bubblewrap's: an install outside it (Homebrew, /Applications)
             # would change the user's machine
             '(deny file-write* (subpath "/"))', '(allow file-write* (subpath "/dev"))',
             f"(deny file-read* file-write* {' '.join(f'(subpath {q(p)})' for p in denied)})",
             # the pasteboard holds whatever the user copied last
             '(deny mach-lookup (global-name "com.apple.pasteboard.1"))',
             f"(allow file-read* file-write* (subpath {q(base)}))",
             f"(deny file-write* (subpath {q(base / 'opt')}))",
             # realpath() of anything in the room lstat()s /private/tmp
             '(allow file-read-metadata (literal "/private/tmp"))']
    if room.run:  # Seatbelt matches resolved paths: /var/folders is /private/var/folders
        rules.append(f"(allow file-read* file-write* (subpath {q(room.run.resolve())}))")
    return "\n".join(rules) + "\n"


def _rmtree(path: Path):
    """Remove a room or a part of it, also where the agent left folders read-only (Go's module cache);
    nothing outside it is touched."""
    root = str(path)

    def writable(function, failed, *_):
        if function not in (os.rmdir, os.unlink, os.remove) or not str(failed).startswith(root):
            return
        try:
            parent = os.path.dirname(failed)
            if parent.startswith(root):
                os.chmod(parent, 0o700)
            function(failed)
        except OSError:
            pass
    if sys.version_info >= (3, 12):
        shutil.rmtree(path, onexc=writable)
    else:
        shutil.rmtree(path, onerror=writable)


def _say(message: str):
    """A line on stderr, which may be gone: a closed terminal, a closed stream, or no stderr at all
    (print would then write to stdout, where a check reads its output)."""
    if sys.stderr is None:
        return
    try:
        print(message, file=sys.stderr)
    except (OSError, ValueError):
        pass


def _number(text: str) -> bool:
    return text.isascii() and text.isdigit()  # isdigit alone takes digits int() does not


def _listing(argv: list[str]) -> str:
    """A listing from ps or lsof; empty when the program is missing, fails or stalls."""
    try:
        return subprocess.run(argv, capture_output=True, timeout=5).stdout.decode(errors="replace")
    except (OSError, subprocess.SubprocessError):
        return ""


def _room_processes(base: Path) -> list[int]:
    """The user's processes that run from the room or in it: their command line names a path in the
    room (a program the agent put there, the sandbox itself), or their working directory is in it.
    A process that does neither, such as a daemon that moved to / and runs a program from outside
    the room, is not found."""
    roots = {str(base), str(base.resolve()), f"/tmp/{base.name}"}  # /tmp is a link to /private/tmp
    pids = set()
    for line in _listing(["/bin/ps", "-xww", "-o", "pid=,command="]).splitlines():
        pid, _, command = line.strip().partition(" ")
        if _number(pid) and any(re.search(rf"(?:(?<![^\s\"'=:<>(;&|])|(?<=file://)){re.escape(root)}(?=[/\s\"';:)<>&|]|$)",
                                          command) for root in roots):
            pids.add(int(pid))
    pid = None
    for line in _listing(["/usr/sbin/lsof", "-b", "-w", "-a", "-u", str(os.getuid()), "-d", "cwd", "-Fpn"]).splitlines():
        if line.startswith("p"):
            pid = int(line[1:]) if _number(line[1:]) else None
        elif line.startswith("n") and pid and any(line[1:] == root or line[1:].startswith(root + "/") for root in roots):
            pids.add(pid)
    return sorted(p for p in pids if p > 1 and p != os.getpid())


def _signal(pid: int, sig: int) -> bool:
    try:
        os.kill(pid, sig)
        return True
    except OSError:
        return False


def _alive(pids: list[int]) -> list[int]:
    """Those of pids still running. A zombie (ended, but not yet reaped by its parent) has ended."""
    existing = []
    for pid in pids:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            continue
        except PermissionError:
            pass
        existing.append(pid)
    if not existing:
        return []
    states = _listing(["/bin/ps", "-o", "pid=,stat=", "-p", ",".join(map(str, existing))])
    zombies = {int(f[0]) for f in (line.split() for line in states.splitlines()) if len(f) == 2 and _number(f[0])
               and f[1].startswith("Z")}
    return [pid for pid in existing if pid not in zombies]


def _end_processes(base: Path, grace: float = 3.0) -> int:
    """End what the agent left running in a Seatbelt room (a browser, a daemon, a server): Seatbelt,
    unlike bubblewrap's own PID namespace, ends nothing with the room. SIGTERM, then SIGKILL for
    whatever still runs after the grace period. Returns how many it ended; it names those that survive."""
    signalled = [pid for pid in _room_processes(base) if _signal(pid, signal.SIGTERM)]
    deadline = time.monotonic() + grace
    alive = signalled
    while alive and time.monotonic() < deadline:
        time.sleep(0.1)
        alive = _alive(alive)
    for pid in alive:
        _signal(pid, signal.SIGKILL)
    deadline = time.monotonic() + 1
    while alive and time.monotonic() < deadline:
        time.sleep(0.05)
        alive = _alive(alive)
    if alive:
        _say(f"tare: {len(alive)} process{'es' if len(alive) != 1 else ''} of the room still run: {', '.join(map(str, alive))}")
    return len(signalled) - len(alive)


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
    """Every entry under `root`, by relative path: its kind and what a change would alter. A socket,
    a pipe or a device is "special": it cannot be copied (git's fsmonitor keeps a socket in .git)."""
    state = {}
    for directory, dirs, files in os.walk(root):
        for name in dirs + files:
            path = Path(directory, name)
            st = path.lstat()
            if stat.S_ISLNK(st.st_mode):
                state[str(path.relative_to(root))] = ("link", os.readlink(path))
            elif stat.S_ISDIR(st.st_mode):
                state[str(path.relative_to(root))] = ("dir", st.st_mode)
            elif stat.S_ISREG(st.st_mode):
                state[str(path.relative_to(root))] = ("file", st.st_mode, st.st_size, st.st_mtime_ns)
            else:
                state[str(path.relative_to(root))] = ("special",)
    return state


def _remove(path: Path):
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path)
    else:
        path.unlink(missing_ok=True)


def _copy_back(before: dict[str, tuple], clone: Path, work: Path):
    """Apply what the run changed in the clone to `work`: new and changed entries are copied over,
    removed ones are removed. An entry the run did not touch stays as it is in `work`, even if
    the user changed it meanwhile. A socket or a pipe the run left is not copied; what it
    replaced counts as removed."""
    after = _state(clone)
    for rel in sorted(before.keys() - after.keys(), reverse=True):  # a directory's entries before the directory
        _remove(work / rel)
    for rel in sorted(after):  # a directory before its entries
        if before.get(rel) == after[rel]:
            continue
        source, target = clone / rel, work / rel
        if after[rel][0] == "special":
            if rel in before:
                _remove(target)
            continue
        if after[rel][0] == "dir":
            if not target.is_dir() or target.is_symlink():
                _remove(target)
                target.mkdir()
            target.chmod(stat.S_IMODE(after[rel][1]))
            continue
        _remove(target)
        try:
            if after[rel][0] == "link":
                target.symlink_to(os.readlink(source))
            else:
                shutil.copy2(source, target)
        except FileNotFoundError:
            if os.path.lexists(source):  # the project's side is missing (the user removed a folder): not ours to hide
                raise
            # gone from the clone since the state was taken


# a room of tare 0.5.0 or older has no lock: in use while anything in it changed within this time
LEGACY_IDLE = 3600  # seconds


def _hold(base: Path):
    """A lock that the room's tare holds from the room's making until it is gone, beside the room
    (out of the agent's reach). `tare cleanup` removes only a room whose lock is free."""
    lock = open(f"{base}.lock", "w")
    fcntl.flock(lock, fcntl.LOCK_EX)
    return lock


def _release(lock, base: Path, kept: bool = False):
    """Let go of a room. Its lock file goes with the room; if the room could not be removed, the lock
    file stays, free, so that `tare cleanup` finds it. A room kept on purpose (the clone of a failed
    copy-back) loses its lock file, so cleanup never takes it."""
    if kept or not os.path.lexists(base):
        Path(f"{base}.lock").unlink(missing_ok=True)
    lock.close()


def rooms_on_disk() -> list[Path]:
    """The user's own room directories: bubblewrap's in the temporary directory, Seatbelt's in
    /private/tmp. Never a link, so nothing a room's name points to elsewhere."""
    places = {Path(tempfile.gettempdir()).resolve(), Path(SEATBELT_ROOMS).resolve()}
    found = set()
    for place in places:
        for p in place.glob("tare-room-*") if place.is_dir() else []:
            try:
                st = p.lstat()
            except OSError:
                continue
            if stat.S_ISDIR(st.st_mode) and st.st_uid == os.getuid():
                found.add(p)
    return sorted(found)


def _newest_change(root: Path) -> float:
    newest = 0.0
    for directory, dirs, files in os.walk(root):
        for name in [*dirs, *files]:
            try:
                newest = max(newest, os.lstat(os.path.join(directory, name)).st_mtime)
            except OSError:
                pass
    try:
        return max(newest, root.lstat().st_mtime)
    except OSError:
        return newest


def in_use(room_dir: Path) -> bool:
    """Whether a tare still holds the room. A room of tare 0.5.0 or older has no lock: it counts as
    in use while anything in it changed within LEGACY_IDLE."""
    lock = Path(f"{room_dir}.lock")
    if not lock.exists():
        return time.time() - _newest_change(room_dir) < LEGACY_IDLE
    try:
        with open(lock) as f:
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
            fcntl.flock(f, fcntl.LOCK_UN)
        return False
    except OSError:  # held by the room's tare (BlockingIOError), or unreadable: leave it
        return True


def leftover_rooms() -> list[Path]:
    """Rooms no tare holds any more: a crash or a failed copy-back leaves them, with their login copy (#187)."""
    return [p for p in rooms_on_disk() if not in_use(p)]


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
