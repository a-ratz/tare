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


def test_a_skill_name_is_the_folder_that_holds_the_file_and_never_a_dot_a_glob_or_a_backup():
    reads = {"./SKILL.md": [], "../SKILL.md": [], "cat skills/greet/SKILL.md.bak": [], "cat x/SKILL.md-old": [],
             "ls skills/*/SKILL.md": [], "cat $DIR/SKILL.md": [], "cat ~/SKILL.md": [], "git show HEAD:greet/SKILL.md": ["greet"],
             "test -f x/SKILL.md && cat x/SKILL.md": ["x"], "cat .agents/skills/grüße/SKILL.md": ["grüße"],
             "/bin/zsh -lc 'cat .agents/skills/greet/SKILL.md'": ["greet"]}
    assert {command: used.skill_reads(command) for command in reads} == reads
    assert used.skill_read("/work/.agents/skills/my skill/SKILL.md") == "my skill"
    assert used.skill_read("/work/skills/ns:greet/SKILL.md") == "ns:greet"
    assert used.skill_read("/work/skills/greet/./SKILL.md") == "greet"
    assert used.skill_read("/work/skills/greet/SKILL.md.bak") is None


def test_a_shell_command_is_read_as_the_shell_reads_it():
    reads = {'cat "skills/my skill/SKILL.md"': ["my skill"], "cat skills/my\\ skill/SKILL.md": ["my skill"],
             "cat $(pwd)/SKILL.md": [], 'cat $(dirname "$0")/SKILL.md': [], "FILE=greet/SKILL.md cat $FILE": ["greet"],
             "dd if=greet/SKILL.md": ["greet"], "tool --path=greet/SKILL.md": ["greet"], "cat <greet/SKILL.md": ["greet"],
             "echo hi;cat greet/SKILL.md": ["greet"], 'bash -c "cat a/SKILL.md b/SKILL.md"': ["a", "b"],
             "cat <<EOF\ndon't\nEOF\ncat x/SKILL.md": ["x"]}
    assert {command: used.skill_reads(command) for command in reads} == reads


def test_heredoc_bodies_shell_flags_and_prose_name_no_skill():
    reads = {"cat <<EOF\nread a/SKILL.md\nEOF\ncat b/SKILL.md": ["b"],  # a heredoc's body is written, not read
             '/bin/zsh -lc "cat << \'EOF\' > a.txt\ndon\'t\nEOF\ncat .agents/skills/greet/SKILL.md\ncat << \'EOF\' > b.txt\nwon\'t\nEOF"': ["greet"],
             "bash -cl 'cat a/SKILL.md b/SKILL.md'": ["a", "b"], "sh -ce 'cat greet/SKILL.md'": ["greet"],
             'wc -c ".agents/skills/my skill/SKILL.md"': ["my skill"],  # -c of a program that is no shell
             'cat "$(dirname /work/foo)/SKILL.md"': [], "x=${p#*/} && cat .agents/skills/greet/SKILL.md": ["greet"],
             'git commit -m "Update greet/SKILL.md"': [], 'echo "a/SKILL.md and b/SKILL.md"': [],
             "rg -g '!greet/SKILL.md' hello": []}
    assert {command: used.skill_reads(command) for command in reads} == reads
    big = '/bin/zsh -lc "cat <<EOF > out.txt && cat a/SKILL.md\n' + ("x" * 80 + "\n") * 13000 + 'EOF"'
    assert used.skill_reads(big) == ["a"]  # quick: the body is gone before the words are read


def test_calls_without_ids_or_names_and_lines_of_another_shape_neither_vanish_nor_break_the_count(tmp_path, capsys):
    stream = (jl({"type": "assistant", "message": {"content": [{"type": "tool_use", "name": "Read",
                                                                "input": {"file_path": "/w/a/SKILL.md"}}]}},
                 {"type": "assistant", "message": {"content": [{"type": "tool_use", "id": None, "name": None, "input": "x"}]}},
                 {"type": "assistant", "message": {"content": "just text"}},
                 {"type": "assistant", "message": {"content": [None, "x"]}},
                 {"type": "assistant", "message": None}, [1, 2])
              + "null\n")
    assert AGENTS["claude"].uses(stream).to_dict() == {"tools": {"Read": 1, "?": 1}, "skills": {"a": 1}}
    assert AGENTS["pi"].uses(jl({"type": "tool_execution_start", "toolName": "read", "args": {"path": "/w/a/SKILL.md"}},
                                {"type": "tool_execution_start", "toolName": None, "args": None})).to_dict() == {
        "tools": {"read": 1, "?": 1}, "skills": {"a": 1}}
    assert AGENTS["codex"].uses(jl({"type": "item.completed", "item": "x"},
                                   {"type": "item.completed", "item": {"type": "mcp_tool_call", "server": None}},
                                   {"type": "item.completed", "item": {"type": "file_change"}},
                                   {"type": "item.completed", "item": {"id": "e", "type": ""}})).to_dict() == {
        "tools": {"?.?": 1, "file_change": 1}, "skills": {}}
    pi = jl({"type": "tool_execution_start", "toolCallId": "", "toolName": "read", "args": {"path": "/w/a/SKILL.md"}},
            {"type": "tool_execution_start", "toolCallId": "", "toolName": "bash", "args": {}},
            {"type": "tool_execution_start", "toolCallId": ["x"], "toolName": ["read"], "args": {}})
    assert AGENTS["pi"].uses(pi).to_dict() == {"tools": {"read": 1, "bash": 1, "['read']": 1}, "skills": {"a": 1}}
    (tmp_path / "stdout.jsonl").write_text(stream)

    class Broken:
        def uses(self, stdout):
            raise KeyError("a shape nobody expected")
    assert caps.read_uses(Broken(), tmp_path) is None  # the run goes on without counts
    assert "no skill and tool counts" in capsys.readouterr().err


def test_agy_counts_a_subagent_step_with_the_same_index_and_takes_the_skill_from_the_report_that_names_it():
    def step(conversation, index, state, tool, **parameters):
        return {"event": "step_update", "step_update": {"conversation_id": conversation, "step_index": index, "state": state,
                                                        "step_type": "tool", "tool_name": tool,
                                                        "tool_info": {"parameters": parameters}}}
    stream = jl(step("main", 2, "ACTIVE", "invoke_subagent"), step("main", 2, "DONE", "invoke_subagent"),
                step("sub", 2, "ACTIVE", "read_file"), step("sub", 2, "DONE", "read_file", Path="/w/greet/SKILL.md"),
                step("sub", 3, "ACTIVE", "run_command", CommandLine="cat /w/review/SKILL.md"),
                step("sub", 3, "DONE", "run_command", CommandLine="cat /w/review/SKILL.md"))
    assert AGENTS["agy"].uses(stream).to_dict() == {"tools": {"invoke_subagent": 1, "read_file": 1, "run_command": 1},
                                                    "skills": {"greet": 1, "review": 1}}
    odd = jl(step("c", "", "DONE", "read_file", Path="/w/a/SKILL.md"), step("c", "", "DONE", "write_file"),
             step(["c"], 1, "DONE", "read_file"))
    assert AGENTS["agy"].uses(odd).to_dict() == {"tools": {"read_file": 2, "write_file": 1}, "skills": {"a": 1}}


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


def test_skills_are_listed_by_how_many_runs_loaded_them_and_null_counts_are_read_as_none():
    start = {"event": "start", "sides": {"a": {"agent": "claude", "args": []}}}
    events = [start, *({"event": "tail", "id": f"a-{i}", "status": "running", "side": "a"} for i in range(3)),
              {"event": "tail", "id": "a-0", "status": "passed", "uses": {"tools": {"Skill": 5}, "skills": {"loud": 5}}},
              {"event": "tail", "id": "a-1", "status": "passed", "uses": {"tools": {"Skill": 1}, "skills": {"common": 1}}},
              {"event": "tail", "id": "a-2", "status": "passed", "uses": {"tools": None, "skills": {"common": 1}}}]
    side = used.of_run(events)["sides"]["a"]
    assert list(side["skills"]) == ["common", "loud"] and side["runs"] == 3
