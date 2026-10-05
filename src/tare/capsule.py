"""Capsules: a run in the room, resumable at every step (epics Cliff and Swap).

During the original run a PostToolUse hook archives /work after every tool call into a
run directory outside the room. A step is one model tool call, or several issued together;
its capsule is the archive taken after its last tool plus the session up to its results.
Capsule 0 is the project before the run. A capsule is continued either natively (the
agent's own session, cut after the step; Claude Code) or by handoff (a fresh session
started with the trail rendered up to the step; every agent).
"""
import hashlib
import json
import shutil
import subprocess
import tarfile
from dataclasses import dataclass
from pathlib import Path

from . import trail as trails
from .room import ROOM_HOME, bwrap, room_home

RUN_MOUNT = "/tare-run"
HOOK_COMMAND = f"/bin/sh {RUN_MOUNT}/hook.sh"
# Archives /work after every tool call, numbered, named by the call's tool_use_id.
# The hook input is JSON on stdin; its top-level tool_use_id is the first one in it.
HOOK = """#!/bin/sh
id=$(grep -o '"tool_use_id": *"[^"]*"' | head -1 | sed 's/.*"\\([^"]*\\)"$/\\1/')
n=$(ls /tare-run/capsules | wc -l)
tar -C /work -cf "/tare-run/capsules/$(printf %04d "$n")-$id.tar" .
"""
CONTINUE = "Continue."


@dataclass
class Capsule:
    step: int
    tool_use_id: str | None  # None for step 0
    archive: Path  # tar of /work; identical workspaces share one archive
    cut: int  # native session lines kept (0 for step 0, or when there is no native resume)
    trail_cut: int  # trail events up to this step
    tool: str  # what the step did, for reports


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


def _config(agent, home: Path) -> Path:
    return home / Path(agent.room_config).relative_to(ROOM_HOME)


def record(agent, real, project: Path, out: Path, prompt: str, args: list[str],
           env: dict[str, str] | None = None) -> int:
    """The original run, in a room, on a copy of the project, with a capsule per tool call.
    Returns the agent's exit code."""
    store = out / "store"
    (store / "capsules").mkdir(parents=True)
    (store / "hook.sh").write_text(HOOK)
    work = out / "original" / "work"
    shutil.copytree(project, work, symlinks=True)
    archive(work, store / "capsules" / "0000-start.tar")
    (out / "original" / "task.txt").write_text(prompt)
    with room_home(agent, real) as home:
        agent.prepare_hook(_config(agent, home), HOOK_COMMAND)
        command = [agent.name, *agent.room_flags, *agent.run_args(prompt, args, hook=HOOK_COMMAND)]
        code = _stream(bwrap(agent, real, home, work, command, env, ["--bind", str(store), RUN_MOUNT]),
                       out / "original", None)
        session = agent.session_file(home)
        if session:
            shutil.copyfile(session, out / "original" / "session.jsonl")
    return code


def _stream(argv: list[str], log_dir: Path, timeout: float | None) -> int:
    """Run a room with the agent's stdout and stderr written to log_dir as they come (the dashboard reads them)."""
    with (log_dir / "stdout.jsonl").open("w") as out, (log_dir / "stderr.log").open("w") as err:
        proc = subprocess.Popen(argv, stdout=out, stderr=err, stdin=subprocess.DEVNULL)
        try:
            return proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
            raise


def session_lines(out: Path) -> list[str]:
    path = out / "original" / "session.jsonl"
    return path.read_text().splitlines() if path.exists() else []


def capsules(out: Path, agent) -> list[Capsule]:
    """The resumable steps of the original run, in order."""
    archives = sorted((out / "store" / "capsules").glob("*.tar"))
    by_id = {path.stem.split("-", 1)[1]: path for path in archives[1:]}
    result = [Capsule(0, None, archives[0], 0, 0, "start")]
    seen = {_digest(archives[0]): archives[0]}
    previous = archives[0]
    for step in agent.trail(session_lines(out)).steps:
        taken = [by_id[i] for i in step.ids if i in by_id]
        # the last snapshot of the step; a step whose tools the hook never saw left the workspace as it was
        path = max(taken) if taken else previous
        shared = seen.setdefault(_digest(path), path)
        if shared != path:
            path.unlink()  # same workspace as an earlier capsule: keep one archive
        result.append(Capsule(len(result), step.ids[-1], shared, step.native_cut or 0, step.trail_cut, step.tool))
        previous = shared
    return result


def session_id(out: Path) -> str:
    for line in session_lines(out):
        entry = json.loads(line)
        # Claude Code: sessionId on every entry; Codex: the session_meta payload; Pi: the session header
        sid = (entry.get("sessionId") or (entry.get("payload") or {}).get("id")
               or (entry.get("id") if entry.get("type") == "session" else None))
        if sid:
            return sid
    raise ValueError("no session id in the session file")


def _run_in(agent, real, home: Path, work: Path, command: list[str], env, timeout: float, log_dir: Path) -> str:
    try:
        return f"agent exit {_stream(bwrap(agent, real, home, work, command, env), log_dir, timeout)}"
    except subprocess.TimeoutExpired:
        return f"agent stopped after {int(timeout)} s"


def _finish(tail_dir: Path, work: Path, step: int, ran: str, check: str, extra: dict | None = None,
            keep: bool = False) -> Tail:
    # without a check (calibrate only) a run counts when its agent ended normally
    passed, detail = run_check(check, work) if check else (ran == "agent exit 0", "no check")
    (tail_dir / "result.json").write_text(json.dumps({"step": step, "passed": passed, "agent": ran, "check": detail,
                                                      **(extra or {})}))
    if not keep:
        shutil.rmtree(work, ignore_errors=True)
    return Tail(step, passed, f"{ran}; {detail}")


def run_tail(agent, real, out: Path, capsule: Capsule, prompt: str, args: list[str], check: str,
             index: int, env: dict[str, str] | None = None, timeout: float = 1800, tail_dir: Path | None = None,
             keep: bool = False) -> Tail:
    """Continue a capsule natively in a fresh room (the agent's own session, cut after the step),
    run it to the end, score the workspace with the check. Step 0 is a fresh start."""
    tail_dir = tail_dir or out / "tails" / f"{capsule.step:04d}-{index}"
    work = tail_dir / "work"
    work.mkdir(parents=True)
    unpack(capsule.archive, work)
    with room_home(agent, real) as home:
        if capsule.step == 0:
            command = [agent.name, *agent.room_flags, *agent.run_args(prompt, args)]
        else:
            sid = session_id(out)
            agent.place_session(home, sid, session_lines(out)[:capsule.cut])
            command = [agent.name, *agent.room_flags, *agent.resume_args(sid, CONTINUE, args)]
        ran = _run_in(agent, real, home, work, command, env, timeout, tail_dir)
    return _finish(tail_dir, work, capsule.step, ran, check, keep=keep)


def run_handoff(agent, real, tail_dir: Path, capsule: Capsule, events: list[trails.Event], task: str,
                args: list[str], check: str, env: dict[str, str] | None = None, workspace_only: bool = False,
                timeout: float = 1800) -> Tail:
    """Continue a capsule by handoff: a fresh session of any agent, in the capsule's workspace,
    started with the trail rendered up to the step."""
    work = tail_dir / "work"
    work.mkdir(parents=True)
    unpack(capsule.archive, work)
    handoff = trails.render(task, events[:capsule.trail_cut], workspace_only)
    (tail_dir / "handoff.txt").write_text(handoff)
    with room_home(agent, real) as home:
        ran = _run_in(agent, real, home, work, [agent.name, *agent.room_flags, *agent.run_args(handoff, args)],
                      env, timeout, tail_dir)
    return _finish(tail_dir, work, capsule.step, ran, check, {"agent_name": agent.name})


def run_check(check: str, work: Path, timeout: float = 600) -> tuple[bool, str]:
    """The user's check, outside the room: exit code 0 passes."""
    try:
        proc = subprocess.run(check, shell=True, cwd=work, capture_output=True, text=True, timeout=timeout,
                              stdin=subprocess.DEVNULL)
    except subprocess.TimeoutExpired:
        return False, f"check timed out after {int(timeout)} s"
    last = next((line.strip() for line in reversed(proc.stdout.splitlines()) if line.strip()), "")
    return proc.returncode == 0, f"check exit {proc.returncode}" + (f": {last[:120]}" if last else "")


def changed_files(before: Path, after: Path) -> list[str]:
    """Paths whose content differs between two capsule archives."""
    a, b = _contents(before), _contents(after)
    return sorted(name for name in a.keys() | b.keys() if a.get(name) != b.get(name))
