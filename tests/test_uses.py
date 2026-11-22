import json
from pathlib import Path

from tare import capsule as caps
from tare.agents import AGENTS

STREAMS = Path(__file__).parent / "streams"


def recorded(agent: str) -> dict:
    """The counts from a stored stream: each agent was asked to "Use the greet skill." in a project
    whose greet skill writes hello.txt (recorded with Claude Code 2.1.330 and Codex 0.166.0 in
    macOS rooms, Pi 1.6.0 and the Antigravity CLI 1.5.13 outside a room)."""
    return AGENTS[agent].uses((STREAMS / f"{agent}-skill.jsonl").read_text()).to_dict()


def test_every_agent_counts_the_skill_it_loaded_and_the_tools_it_called_from_a_recorded_stream():
    assert recorded("claude") == {"tools": {"Skill": 1, "Write": 1}, "skills": {"greet": 1}}
    assert recorded("codex") == {"tools": {"command_execution": 2}, "skills": {"greet": 1}}
    assert recorded("pi") == {"tools": {"bash": 2, "read": 1}, "skills": {"greet": 1}}
    assert recorded("agy") == {"tools": {"read_file": 1, "write_file": 1}, "skills": {"greet": 1}}


def jl(*events) -> str:
    return "".join(json.dumps(e) + "\n" for e in events)


def test_a_read_of_a_skill_file_counts_as_a_load_and_a_write_does_not():
    def tool(i, name, **args):
        return {"type": "assistant", "message": {"content": [{"type": "tool_use", "id": i, "name": name, "input": args}]}}
    stream = jl(tool("t1", "Read", file_path="/work/.claude/skills/review/SKILL.md"),
                tool("t2", "Bash", command="cat skills/a/SKILL.md skills/b/SKILL.md"),
                tool("t3", "Write", file_path="/work/skills/c/SKILL.md", content="x"),
                tool("t4", "Bash", command="ls skills/*/SKILL.md"),
                tool("t1", "Read", file_path="/work/.claude/skills/review/SKILL.md"))  # the same call again
    assert AGENTS["claude"].uses(stream).to_dict() == {"tools": {"Bash": 2, "Read": 1, "Write": 1},
                                                       "skills": {"review": 1, "a": 1, "b": 1}}


def test_codex_counts_each_item_once_and_names_an_mcp_call_by_server_and_tool():
    stream = jl({"type": "item.started", "item": {"id": "i1", "type": "command_execution", "command": "cat x/SKILL.md"}},
                {"type": "item.completed", "item": {"id": "i1", "type": "command_execution", "command": "cat x/SKILL.md"}},
                {"type": "item.completed", "item": {"id": "i2", "type": "agent_message", "text": "done"}},
                {"type": "item.completed", "item": {"id": "i3", "type": "mcp_tool_call", "server": "docs", "tool": "search"}},
                {"type": "item.completed", "item": {"id": "i4", "type": "file_change", "changes": []}})
    assert AGENTS["codex"].uses(stream).to_dict() == {
        "tools": {"command_execution": 1, "docs.search": 1, "file_change": 1}, "skills": {"x": 1}}


def test_a_run_whose_stream_is_missing_counts_nothing(tmp_path):
    assert caps.read_uses(AGENTS["pi"], tmp_path) == {"tools": {}, "skills": {}}
    assert caps.read_uses(object(), tmp_path) is None

