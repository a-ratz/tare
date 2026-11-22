"""Uses: which skills a run loaded and which tools it called (epic Which skills and tools a run used).

Each adapter reads its agent's stream after a run into one shape: tool calls by tool name, and
skill loads by skill name. The stream is the record every run keeps (Calibrate keeps no session
file), and it shows each tool call with its arguments.

A skill counts as loaded when the agent invoked it (Claude Code's Skill tool) or read its
SKILL.md: with a read tool, or with a shell command that names the file (Codex has no other way).
The skill's name is the folder that holds the SKILL.md. A load says nothing about whether the
agent then followed the skill: loaded, not followed.

The counts are a by-product of a run: a stream they cannot read leaves a run without counts, it
never fails the run.
"""
import json
import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import PurePosixPath

# a SKILL.md named in a shell command, and the folder that holds it: the last path segment before
# it, not a SKILL.md.bak or SKILL.md-old, and not a glob or a variable (skills/*/SKILL.md, $DIR/SKILL.md)
SKILL_FILE = re.compile(r"""(?:^|(?<=[\s/'"=:(]))([^\s/'"\\*?\[\]{}$]+)/SKILL\.md(?![\w.\-/])""")


def _name(folder: str) -> str | None:
    folder = folder.rsplit(":", 1)[-1]  # git show HEAD:greet/SKILL.md
    return None if folder in ("", ".", "..") else folder


def skill_read(path: str) -> str | None:
    """The skill whose SKILL.md a read tool read: its folder, whatever characters the name has."""
    path = PurePosixPath(path)
    return _name(path.parent.name) if path.name == "SKILL.md" else None


def skill_reads(command: str) -> list[str]:
    """The skills whose SKILL.md a shell command names, by folder, each once per command. A name
    with a space comes through only from a read tool's path."""
    found = []
    for folder in SKILL_FILE.findall(command):
        if (name := _name(folder)) and name not in found:
            found.append(name)
    return found


@dataclass
class Uses:
    tools: Counter = field(default_factory=Counter)
    skills: Counter = field(default_factory=Counter)

    def call(self, tool: str, path: str = "", command: str = "", skill: str | None = None):
        """One tool call: `path` for a read tool, `command` for a shell tool, `skill` for a skill tool."""
        self.tools[tool] += 1
        self.load(path, command, skill)

    def load(self, path: str = "", command: str = "", skill: str | None = None) -> bool:
        """The skills a call loaded; True if it loaded any."""
        found = [skill] if skill else []
        if path and (name := skill_read(path)):
            found.append(name)
        found += skill_reads(command) if command else []
        self.skills.update(found)
        return bool(found)

    def to_dict(self) -> dict:
        return {"tools": dict(self.tools.most_common()), "skills": dict(self.skills.most_common())}


def of_run(events: list[dict]) -> dict:
    """Per side, from a run's journal: how many finished runs it has, and for each skill and tool
    in how many of them it appeared and how often in all. Runs whose agent cannot tell are left out."""
    owner: dict[str, str] = {}  # run id -> side key, from the event that started it
    labels: dict[str, str] = {}
    sides: dict[str, dict] = {}
    for e in events:
        kind = e.get("event")
        if kind == "start":
            labels = {k: " ".join([v.get("agent", "?"), *v.get("args", [])]) for k, v in (e.get("sides") or {}).items()}
            sides = {k: {"label": label, "runs": 0, "skills": {}, "tools": {}} for k, label in labels.items()}
        elif kind == "tail" and e.get("status") == "running":
            owner[e["id"]] = e.get("side") or e.get("agent") or "?"
        elif kind == "tail" and isinstance(e.get("uses"), dict):
            side = sides.setdefault(owner.get(e["id"], "?"), {"label": "?", "runs": 0, "skills": {}, "tools": {}})
            side["runs"] += 1
            for what in ("skills", "tools"):
                for name, n in (e["uses"].get(what) or {}).items():
                    found = side[what].setdefault(name, {"runs": 0, "calls": 0})
                    found["runs"] += 1
                    found["calls"] += n
    for side in sides.values():  # skills by how many runs loaded them, tools by how often they were called
        side["skills"] = dict(sorted(side["skills"].items(), key=lambda i: (-i[1]["runs"], -i[1]["calls"], i[0])))
        side["tools"] = dict(sorted(side["tools"].items(), key=lambda i: (-i[1]["calls"], i[0])))
    return {"sides": sides}


def _per_run(calls: int, runs: int) -> str:
    return f"{calls / runs:.1f}"


def report(out) -> list[str]:
    """The skill and tool lines of a Calibrate report, per side. Also writes uses.json into the run
    directory."""
    from . import journal as journals
    summary = of_run(journals.read(out))
    (out / "uses.json").write_text(json.dumps(summary, indent=2) + "\n")
    sides = [(k, s) for k, s in sorted(summary["sides"].items()) if s["runs"]]
    if not sides:
        return []
    skills = [f"{k}  " + (" · ".join(f"{name} in {v['runs']} of {s['runs']} runs, {_per_run(v['calls'], s['runs'])} per run"
                                    for name, v in s["skills"].items()) or "none loaded") for k, s in sides]
    tools = [f"{k}  " + (" · ".join(f"{name} {_per_run(v['calls'], s['runs'])}" for name, v in s["tools"].items())
                         + " per run" if s["tools"] else "none called") for k, s in sides]
    return ["", f"  skills    {skills[0]}", *[f"            {line}" for line in skills[1:]],
            f"  tools     {tools[0]}", *[f"            {line}" for line in tools[1:]]]
