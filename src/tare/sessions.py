"""Sessions kept after a room closes, so that `tare <agent> --continue` can resume them (epic #194).

A room's home, and with it the agent's session and its login copy, is removed when the room closes.
Before that, tare copies the agent's latest session out of the room into the store, by agent and
project, and keeps it until `tare cleanup`. A later `tare <agent> --continue` places it into a
fresh room the way the agent keeps its sessions, and starts the agent resuming it. The room is
probed before the session is placed, as always. The store is the user's alone (folders 700, files
600): a session holds the whole conversation.
"""
import hashlib
import json
import os
import re
import shutil
import stat
import time
from pathlib import Path

# a session id as the agents write them (UUIDs and the like); anything else could name a path
SAFE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}")  # whole, with fullmatch


def root() -> Path:
    return Path.home() / ".local" / "state" / "tare" / "sessions"


def store(agent, project: Path) -> Path:
    """Where an agent's kept sessions of a project live: the path made readable, and a digest of it,
    so that /a/my-app and /a/my_app do not share one."""
    path = str(project.resolve())
    readable = re.sub(r"[^A-Za-z0-9]", "-", path)[-80:]
    return root() / agent.name / f"{readable}-{hashlib.sha256(path.encode()).hexdigest()[:12]}"


def session_id(lines: list[str]) -> str | None:
    """The session's id from its file: Claude Code's sessionId on every entry, Codex's session_meta
    payload, Pi's session header. None when there is none, or none that is safe as a file name."""
    for line in lines:
        try:
            entry = json.loads(line)
        except ValueError:
            continue
        if not isinstance(entry, dict):
            continue
        meta = entry.get("type") == "session_meta" and isinstance(entry.get("payload"), dict)
        sid = entry.get("sessionId") or (entry["payload"].get("id") if meta else None) \
            or (entry.get("id") if entry.get("type") == "session" else None)
        if isinstance(sid, str) and sid:
            return sid if SAFE_ID.fullmatch(sid) else None
    return None


def lines_of(text: str) -> list[str]:
    """A JSONL file's lines: split at newlines only. A JSON string may hold U+2028 and the like,
    which str.splitlines() would split at too."""
    return [line.removesuffix("\r") for line in text.split("\n") if line.strip()]


def _private(folder: Path):
    """The store's folders, made for the user only."""
    levels = [p for p in reversed(folder.parents) if p.is_relative_to(root()) and p != root()]
    for d in [root(), *levels, folder]:
        d.mkdir(mode=0o700, parents=True, exist_ok=True)
        d.chmod(0o700)


def keep(agent, room, project: Path) -> Path | None:
    """Copy the room's latest session into the store before the room is removed; None when the
    agent cannot continue a session, keeps none, or wrote none. Nothing in the store is removed
    but by `tare cleanup`."""
    if not hasattr(agent, "continue_args"):
        return None
    find = getattr(agent, "latest_session", None) or getattr(agent, "session_file", None)
    found = find(room.home) if find else None
    if found is None or not found.is_file():
        return None
    sid = session_id(lines_of(found.read_text(errors="replace")))
    if sid is None:
        return None
    folder = store(agent, project)
    _private(folder)
    target = folder / f"{time.strftime('%Y%m%d-%H%M%S')}-{sid}.jsonl"
    part = folder / f".{target.name}.part"  # not a *.jsonl: a copy that fails half-way is never the latest
    fd = os.open(part, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)  # the user's alone from the start
    try:
        with os.fdopen(fd, "wb") as out, found.open("rb") as source:
            shutil.copyfileobj(source, out)
        os.replace(part, target)
    except BaseException:
        part.unlink(missing_ok=True)
        raise
    return target


def kept() -> list[Path]:
    """Every kept session, of every agent and project: regular files two folders below the store,
    links not followed."""
    if not root().is_dir() or root().is_symlink():
        return []
    found = []
    for directory, dirs, files in os.walk(root()):  # os.walk does not follow links to folders
        for name in files:
            path = Path(directory, name)
            if (path.suffix == ".jsonl" and len(path.relative_to(root()).parts) == 3
                    and stat.S_ISREG(path.lstat().st_mode)):
                found.append(path)
    return sorted(found)


def remove_empty_folders():
    """The store's folders that `tare cleanup` emptied; never through a link."""
    if not root().is_dir() or root().is_symlink():
        return
    for directory, dirs, files in os.walk(root(), topdown=False):
        path = Path(directory)
        if path != root() and not path.is_symlink() and not any(path.iterdir()):
            path.rmdir()


def latest(agent, project: Path) -> Path | None:
    """The latest kept session of an agent in a project."""
    folder = store(agent, project)
    if not folder.is_dir() or folder.is_symlink():
        return None
    found = sorted(p for p in folder.glob("*.jsonl") if stat.S_ISREG(p.lstat().st_mode))
    return found[-1] if found else None


def read(path: Path) -> tuple[str, list[str]]:
    """A kept session's id and lines, for --continue; ValueError when it holds no safe id."""
    lines = lines_of(path.read_text(errors="replace"))
    sid = session_id(lines)
    if sid is None:
        raise ValueError(f"no session id in {path}")
    return sid, lines
