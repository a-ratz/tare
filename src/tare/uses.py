"""Uses: which skills a run loaded and which tools it called (epic Which skills and tools a run used).

Each adapter reads its agent's stream after a run into one shape: tool calls by tool name, and
skill loads by skill name. The stream is the record every run keeps (Calibrate keeps no session
file), and it shows each tool call with its arguments.

A skill counts as loaded when the agent invoked it (Claude Code's Skill tool) or read its
SKILL.md: with a read tool, or with a shell command that names the file (Codex has no other way).
The skill's name is the folder that holds the SKILL.md. A load says nothing about whether the
agent then followed the skill: loaded, not followed.
"""
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

