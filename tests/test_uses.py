import json
from pathlib import Path

from tare import calibrate as cal
from tare import capsule as caps
from tare import dashboard
from tare import uses as used
from tare.agents import AGENTS
from tare.journal import Journal

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


class Named:
    def __init__(self, name):
        self.name = name


def test_the_report_dashboard_and_run_directory_hold_the_counts_per_side(tmp_path, monkeypatch):
    project = tmp_path / "project"
    project.mkdir()
    (project / "README.md").write_text("x")
    out = tmp_path / "run"
    out.mkdir()
    runs = {"claude": iter([{"tools": {"Skill": 1, "Write": 1}, "skills": {"greet": 1}},
                            {"tools": {"Skill": 2, "Bash": 3}, "skills": {"greet": 1, "review": 1}},
                            {"tools": {"Write": 1}, "skills": {}}]),
            "codex": iter([{"tools": {"command_execution": 2}, "skills": {}}] * 3)}

    def fake_tail(agent, real, out_, capsule, prompt, args, check, i, env=None, timeout=1800, tail_dir=None, keep=False):
        return caps.Tail(0, True, "d", uses=next(runs[agent.name]))

    monkeypatch.setattr(caps, "run_tail", fake_tail)
    sides = [cal.Side("a", Named("claude"), None, []), cal.Side("b", Named("codex"), None, [])]
    text = cal.calibrate(sides, project, "task", "check", out, runs=3, jobs=1, journal=Journal(out))
    assert "  skills    a  greet in 2 of 3 runs, 0.7 per run · review in 1 of 3 runs, 0.3 per run" in text
    assert "            b  none loaded" in text
    assert "  tools     a  Bash 1.0 · Skill 1.0 · Write 0.7 per run" in text
    assert "            b  command_execution 2.0 per run" in text
    stored = json.loads((out / "uses.json").read_text())
    assert stored["sides"]["a"]["skills"]["greet"] == {"runs": 2, "calls": 2}
    assert stored["sides"]["b"]["runs"] == 3
    assert dashboard.state(out)["uses"] == stored


def test_a_run_still_going_is_not_counted_and_sides_whose_agent_cannot_tell_have_no_lines():
    start = {"event": "start", "sides": {"a": {"agent": "claude", "args": []}, "b": {"agent": "x", "args": []}}}
    events = [start, {"event": "tail", "id": "a-0", "status": "running", "side": "a"},
              {"event": "tail", "id": "a-1", "status": "running", "side": "a"},
              {"event": "tail", "id": "a-0", "status": "passed", "uses": {"tools": {"Read": 2}, "skills": {"s": 1}}},
              {"event": "tail", "id": "b-0", "status": "running", "side": "b"},
              {"event": "tail", "id": "b-0", "status": "passed", "uses": None}]
    sides = used.of_run(events)["sides"]
    assert sides["a"] == {"label": "claude", "runs": 1, "skills": {"s": {"runs": 1, "calls": 1}},
                          "tools": {"Read": {"runs": 1, "calls": 2}}}
    assert sides["b"]["runs"] == 0
