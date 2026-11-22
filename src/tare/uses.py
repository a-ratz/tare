"""Uses: which skills a run loaded and which tools it called (epic Which skills and tools a run used).

Each adapter reads its agent's stream after a run into one shape: tool calls by tool name, and
skill loads by skill name. The stream is the record every run keeps (Calibrate keeps no session
file), and it shows each tool call with its arguments.

A skill counts as loaded when the agent invoked it (Claude Code's Skill tool) or read its
SKILL.md: with a read tool, or with a shell command that names the file (Codex has no other way).
The skill's name is the folder that holds the SKILL.md. A load says nothing about whether the
agent then followed the skill: loaded, not followed.
"""
import json
import re
from collections import Counter
from dataclasses import dataclass, field

# a SKILL.md named in a path or a command, and the folder that holds it
SKILL_FILE = re.compile(r"([A-Za-z0-9_.:-]+)/SKILL\.md\b")


def skill_reads(text: str) -> list[str]:
    """The skills whose SKILL.md a path or a shell command names, by folder."""
    return SKILL_FILE.findall(text)


@dataclass
class Uses:
    tools: Counter = field(default_factory=Counter)
    skills: Counter = field(default_factory=Counter)

    def call(self, tool: str, reads: str = "", skill: str | None = None):
        """One tool call. `reads` is the path or command of a call that reads files, `skill` the
        skill a skill tool invoked."""
        self.tools[tool] += 1
        if skill:
            self.skills[skill] += 1
        self.skills.update(skill_reads(reads))

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
        elif kind == "tail" and e.get("uses") is not None:
            side = sides.setdefault(owner.get(e["id"], "?"), {"label": "?", "runs": 0, "skills": {}, "tools": {}})
            side["runs"] += 1
            for what in ("skills", "tools"):
                for name, n in e["uses"].get(what, {}).items():
                    found = side[what].setdefault(name, {"runs": 0, "calls": 0})
                    found["runs"] += 1
                    found["calls"] += n
    for side in sides.values():
        for what in ("skills", "tools"):
            side[what] = dict(sorted(side[what].items(), key=lambda item: (-item[1]["calls"], item[0])))
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
