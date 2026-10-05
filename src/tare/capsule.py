"""Capsules: a run in the room, resumable at every tool call (epic Cliff).

During the original run a PostToolUse hook archives /work after every tool call into a
run directory outside the room. Together with the session transcript cut right after
that call's tool result, an archive is a capsule: a tail resumed from it starts from
exactly that workspace and that conversation. Capsule 0 is the project before the run;
its tail is a fresh start with the original prompt.

Claude Code only for now.
"""
import hashlib
import json
import shutil
import subprocess
import tarfile
from dataclasses import dataclass
from pathlib import Path

from .room import bwrap, room_home

RUN_MOUNT = "/tare-run"
# Archives /work after every tool call, numbered, named by the call's tool_use_id.
# The hook input is JSON on stdin; its top-level tool_use_id is the first one in it.
HOOK = """#!/bin/sh
id=$(grep -o '"tool_use_id": *"[^"]*"' | head -1 | sed 's/.*"\\([^"]*\\)"$/\\1/')
n=$(ls /tare-run/capsules | wc -l)
tar -C /work -cf "/tare-run/capsules/$(printf %04d "$n")-$id.tar" .
"""
HOOK_SETTINGS = json.dumps({"hooks": {"PostToolUse": [
    {"matcher": "", "hooks": [{"type": "command", "command": f"/bin/sh {RUN_MOUNT}/hook.sh"}]}]}})
CONTINUE = "Continue."


@dataclass
class Capsule:
    step: int
    tool_use_id: str | None  # None for step 0
    archive: Path  # tar of /work; identical workspaces share one archive
    cut: int  # transcript lines kept (0 for step 0)
    tool: str  # what the step did, for the report


@dataclass
class Tail:
    step: int
    passed: bool
    detail: str


def _contents(path: Path) -> dict[str, str]:
    """Path -> content digest of every file in a capsule archive (not its timestamps)."""
    with tarfile.open(path) as tar:
        return {m.name.removeprefix("./"): hashlib.sha256(tar.extractfile(m).read()).hexdigest()
                for m in tar.getmembers() if m.isfile()}


def _digest(path: Path) -> str:
    return hashlib.sha256(json.dumps(sorted(_contents(path).items())).encode()).hexdigest()


def archive(directory: Path, target: Path):
    with tarfile.open(target, "w") as tar:
        tar.add(directory, arcname=".")


def unpack(source: Path, directory: Path):
    with tarfile.open(source) as tar:
        tar.extractall(directory, filter="tar")


def _claude_args(agent, extra: list[str]) -> list[str]:
    return ["claude", *agent.room_flags, "--dangerously-skip-permissions", *extra]


def record(agent, real, project: Path, out: Path, prompt: str, claude_args: list[str],
           env: dict[str, str] | None = None) -> subprocess.CompletedProcess:
    """The original run, in a room, on a copy of the project, with a capsule per tool call."""
    store = out / "store"
    (store / "capsules").mkdir(parents=True)
    (store / "hook.sh").write_text(HOOK)
    work = out / "original" / "work"
    shutil.copytree(project, work, symlinks=True)
    archive(work, store / "capsules" / "0000-start.tar")
    with room_home(agent, real) as home:
        argv = bwrap(agent, real, home, work,
                     [*_claude_args(agent, ["--settings", HOOK_SETTINGS, *claude_args]), "-p", prompt,
                      "--output-format", "stream-json", "--verbose"],
                     env, ["--bind", str(store), RUN_MOUNT])
        proc = subprocess.run(argv, capture_output=True, text=True, stdin=subprocess.DEVNULL)
        sessions = sorted((home / ".claude-config" / "projects").rglob("*.jsonl"), key=lambda p: p.stat().st_size)
        if sessions:
            shutil.copyfile(sessions[-1], out / "original" / "transcript.jsonl")
    (out / "original" / "stdout.jsonl").write_text(proc.stdout)
    return proc


def _describe(block: dict) -> str:
    args = block.get("input", {})
    detail = args.get("command") or args.get("file_path") or args.get("pattern") or args.get("description") or ""
    return f"{block.get('name', '?')} {str(detail).splitlines()[0][:70] if detail else ''}".strip()


def capsules(out: Path) -> list[Capsule]:
    """The resumable steps of the original run, in order."""
    store = out / "store" / "capsules"
    archives = sorted(store.glob("*.tar"))
    lines = (out / "original" / "transcript.jsonl").read_text().splitlines()
    entries = [json.loads(line) for line in lines]

    # where each tool call was made and where its result was written
    made_in: dict[str, int] = {}
    described: dict[str, str] = {}
    result_at: dict[str, int] = {}
    for i, entry in enumerate(entries):
        content = (entry.get("message") or {}).get("content")
        if not isinstance(content, list):
            continue
        for block in content:
            if block.get("type") == "tool_use":
                made_in[block["id"]] = i
                described[block["id"]] = _describe(block)
            elif block.get("type") == "tool_result":
                result_at[block["tool_use_id"]] = i

    result = [Capsule(0, None, archives[0], 0, "start")]
    seen = {_digest(archives[0]): archives[0]}
    pending: dict[int, list[tuple[str, Path]]] = {}
    for path in archives[1:]:
        tool_use_id = path.stem.split("-", 1)[1]
        if tool_use_id not in made_in or tool_use_id not in result_at:
            continue  # a subagent's call, or one whose result never reached the transcript
        pending.setdefault(made_in[tool_use_id], []).append((tool_use_id, path))
    # parallel calls in one assistant message are one step: resumable only after the last result
    for _, calls in sorted(pending.items()):
        tool_use_id, path = max(calls, key=lambda c: result_at[c[0]])
        cut = max(result_at[c[0]] for c in calls) + 1
        digest = _digest(path)
        shared = seen.setdefault(digest, path)
        if shared != path:
            path.unlink()  # same workspace as an earlier capsule: keep one archive
        tool = " + ".join(described[c[0]] for c in calls)
        result.append(Capsule(len(result), tool_use_id, shared, cut, tool))
    return result


def session_id(out: Path) -> str:
    for line in (out / "original" / "transcript.jsonl").read_text().splitlines():
        sid = json.loads(line).get("sessionId")
        if sid:
            return sid
    raise ValueError("no session id in the transcript")


def run_tail(agent, real, out: Path, capsule: Capsule, prompt: str, claude_args: list[str], check: str,
             index: int, env: dict[str, str] | None = None, timeout: float = 1800) -> Tail:
    """Resume a capsule in a fresh room, run it to the end, score the workspace with the check."""
    tail_dir = out / "tails" / f"{capsule.step:04d}-{index}"
    work = tail_dir / "work"
    work.mkdir(parents=True)
    unpack(capsule.archive, work)
    with room_home(agent, real) as home:
        if capsule.step == 0:
            command = [*_claude_args(agent, claude_args), "-p", prompt]
        else:
            sid = session_id(out)
            sessions = home / ".claude-config" / "projects" / "-work"
            sessions.mkdir(parents=True)
            lines = (out / "original" / "transcript.jsonl").read_text().splitlines()[:capsule.cut]
            (sessions / f"{sid}.jsonl").write_text("\n".join(lines) + "\n")
            command = [*_claude_args(agent, claude_args), "-p", "--resume", sid, CONTINUE]
        try:
            proc = subprocess.run(bwrap(agent, real, home, work, command, env), capture_output=True, text=True,
                                  timeout=timeout, stdin=subprocess.DEVNULL)
            ran = f"agent exit {proc.returncode}"
        except subprocess.TimeoutExpired:
            ran = f"agent stopped after {int(timeout)} s"
    passed, detail = run_check(check, work)
    (tail_dir / "result.json").write_text(json.dumps({"step": capsule.step, "passed": passed, "agent": ran,
                                                      "check": detail}))
    shutil.rmtree(work, ignore_errors=True)
    return Tail(capsule.step, passed, f"{ran}; {detail}")


def run_check(check: str, work: Path, timeout: float = 600) -> tuple[bool, str]:
    """The user's check, outside the room: exit code 0 passes."""
    try:
        proc = subprocess.run(check, shell=True, cwd=work, capture_output=True, text=True, timeout=timeout,
                              stdin=subprocess.DEVNULL)
    except subprocess.TimeoutExpired:
        return False, f"check timed out after {int(timeout)} s"
    return proc.returncode == 0, f"check exit {proc.returncode}"


def changed_files(before: Path, after: Path) -> list[str]:
    """Paths whose content differs between two capsule archives."""
    a, b = _contents(before), _contents(after)
    return sorted(name for name in a.keys() | b.keys() if a.get(name) != b.get(name))
