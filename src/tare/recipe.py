"""Recipes: how to repeat a Cliff or Swap run exactly.

Every run directory gets a recipe.json: the command, the task and check, a digest of the
project as it was, the agents with their CLI versions and arguments, and the parameters.
`tare rerun DIR` repeats the command and says what has changed since.
"""
import hashlib
import json
import os
import subprocess
import time
from importlib import metadata
from pathlib import Path

# directories that hold tooling, not the project's content
SKIP = {".git", ".venv", "venv", "node_modules", "__pycache__", ".pytest_cache", ".ruff_cache"}


def project_digest(project: Path) -> str:
    digest = hashlib.sha256()
    for root, dirs, files in os.walk(project):
        dirs[:] = sorted(d for d in dirs if d not in SKIP)
        for name in sorted(files):
            path = Path(root) / name
            if path.is_symlink() or not path.is_file():
                continue
            digest.update(str(path.relative_to(project)).encode() + b"\0")
            digest.update(hashlib.sha256(path.read_bytes()).digest())
    return digest.hexdigest()


def cli_version(real) -> str:
    try:
        proc = subprocess.run([str(real.binary), "--version"], capture_output=True, text=True, timeout=30,
                              stdin=subprocess.DEVNULL)
        return (proc.stdout or proc.stderr).strip().splitlines()[0]
    except (OSError, subprocess.TimeoutExpired, IndexError):
        return "unknown"


def tare_version() -> str:
    try:
        return metadata.version("tare-cli")
    except metadata.PackageNotFoundError:
        return "unknown"


def without_out(argv: list[str]) -> list[str]:
    """The command without its --out, so a rerun gets a run directory of its own."""
    result, skip = [], False
    for i, arg in enumerate(argv):
        if skip:
            skip = False
            continue
        if arg == "--":
            return result + argv[i:]
        if arg == "--out":
            skip = True
            continue
        if not arg.startswith("--out="):
            result.append(arg)
    return result


def with_out(argv: list[str], out: Path) -> list[str]:
    at = argv.index("--") if "--" in argv else len(argv)
    return argv[:at] + ["--out", str(out)] + argv[at:]


def write(out: Path, argv: list[str], kind: str, project: Path, task: str, check: str,
          agents: dict[str, tuple[object, object, list[str]]], params: dict) -> dict:
    recipe = {
        "kind": kind, "argv": without_out(argv), "out": str(out), "created": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "tare": tare_version(), "task": task, "check": check, "project": str(project),
        "project_digest": project_digest(project),
        "agents": {key: {"name": agent.name, "args": args, "version": cli_version(real)}
                   for key, (agent, real, args) in agents.items()},
        "params": params,
    }
    (out / "recipe.json").write_text(json.dumps(recipe, indent=2, ensure_ascii=False) + "\n")
    return recipe


def read(out: Path) -> dict:
    return json.loads((out / "recipe.json").read_text())


def drift(recipe: dict, reals: dict[str, object]) -> list[str]:
    """What is no longer as it was when the recipe was written."""
    notes = []
    project = Path(recipe["project"])
    if not project.is_dir():
        notes.append(f"the project {project} is gone")
    elif project_digest(project) != recipe["project_digest"]:
        notes.append(f"the project {project} has changed since the recipe was written")
    for key, agent in recipe["agents"].items():
        real = reals.get(agent["name"])
        if real is not None and (now := cli_version(real)) != agent["version"]:
            notes.append(f"agent {key} ({agent['name']}) was {agent['version']}, is now {now}")
    if (now := tare_version()) != recipe["tare"]:
        notes.append(f"tare was {recipe['tare']}, is now {now}")
    return notes
