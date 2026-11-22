"""Sessions kept after a room closes, so that `tare <agent> --continue` can resume them (epic #194).

A room's home, and with it the agent's session and its login copy, is removed when the room closes.
Before that, tare copies the agent's latest session out of the room into the store, by agent and
project, and keeps it until `tare cleanup`. A later `tare <agent> --continue` places it into a
fresh room the way the agent keeps its sessions, and starts the agent resuming it. The room is
probed before the session is placed, as always.
"""
import json
import re
import shutil
import time
from pathlib import Path


def root() -> Path:
    return Path.home() / ".local" / "state" / "tare" / "sessions"


def store(agent, project: Path) -> Path:
    """Where an agent's kept sessions of a project live."""
    return root() / agent.name / re.sub(r"[^A-Za-z0-9]", "-", str(project.resolve()))


def session_id(lines: list[str]) -> str | None:
    """The session's id from its file. Claude Code: sessionId on every entry; Codex: the
    session_meta payload; Pi: the session header."""
    for line in lines:
        try:
            entry = json.loads(line)
        except ValueError:
            continue
        if not isinstance(entry, dict):
            continue
        payload = entry.get("payload") if isinstance(entry.get("payload"), dict) else {}
        sid = entry.get("sessionId") or payload.get("id") or (entry.get("id") if entry.get("type") == "session" else None)
        if isinstance(sid, str) and sid:
            return sid
    return None


def keep(agent, room, project: Path) -> Path | None:
    """Copy the room's latest session into the store before the room is removed; None when the
    agent keeps none or wrote none. Nothing in the store is removed but by `tare cleanup`."""
    find = getattr(agent, "latest_session", None) or getattr(agent, "session_file", None)
    found = find(room.home) if find else None
    if found is None or not found.is_file():
        return None
    sid = session_id(found.read_text(errors="replace").splitlines())
    if sid is None:
        return None
    folder = store(agent, project)
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / f"{time.strftime('%Y%m%d-%H%M%S')}-{sid}.jsonl"
    shutil.copyfile(found, target)
    target.chmod(0o600)
    return target


def kept() -> list[Path]:
    """Every kept session, of every agent and project."""
    return sorted(root().glob("*/*/*.jsonl")) if root().is_dir() else []


def latest(agent, project: Path) -> Path | None:
    """The latest kept session of an agent in a project."""
    found = sorted(store(agent, project).glob("*.jsonl"))
    return found[-1] if found else None
