import json
import subprocess

from tare import trail as trails
from tare.agents import Antigravity

# the shape of an agy transcript_full.jsonl, as recorded with agy 1.2.16
TRANSCRIPT = [
    {"step_index": 0, "source": "USER_EXPLICIT", "type": "USER_INPUT", "content": "<USER_REQUEST>\nmake hello\n</USER_REQUEST>"},
    {"step_index": 1, "source": "MODEL", "type": "PLANNER_RESPONSE", "tool_calls": [
        {"name": "write_to_file", "args": {"TargetFile": "/work/hello.txt", "CodeContent": "hi\n"}}]},
    {"step_index": 2, "source": "MODEL", "type": "GENERIC", "content": "Created file file:///work/hello.txt"},
    {"step_index": 3, "source": "MODEL", "type": "PLANNER_RESPONSE", "content": "Now both checks.", "tool_calls": [
        {"name": "run_command", "args": {"CommandLine": "cat hello.txt"}},
        {"name": "view_file", "args": {"AbsolutePath": "/work/hello.txt"}}]},
    {"step_index": 4, "source": "MODEL", "type": "GENERIC", "content": "hi"},
    {"step_index": 5, "source": "MODEL", "type": "GENERIC", "content": "1: hi"},
    {"step_index": 6, "source": "MODEL", "type": "PLANNER_RESPONSE", "content": "Done."},
]


def test_agy_transcript_becomes_a_trail_with_one_step_per_planner_response():
    trail = trails.agy([json.dumps(e) for e in TRANSCRIPT])
    assert [(s.ids, s.tool) for s in trail.steps] == [
        (["step-2"], "write_to_file /work/hello.txt"),
        (["step-4", "step-5"], "run_command cat hello.txt + view_file /work/hello.txt")]
    assert [e.kind for e in trail.events] == ["call", "result", "say", "call", "call", "result", "result", "say"]
    assert trail.steps[1].trail_cut == 7 and trail.steps[0].native_cut is None


def test_agy_hook_names_each_snapshot_after_the_step_index_and_answers_with_an_empty_object(tmp_path):
    config = tmp_path / ".gemini" / "antigravity-cli"
    config.mkdir(parents=True)
    Antigravity().prepare_hook(config, "cat")  # the real hook archives /work; cat shows what it is given
    hooks = json.loads((tmp_path / ".gemini" / "config" / "hooks.json").read_text())
    command = hooks["tare-snapshot"]["PostToolUse"][0]["hooks"][0]["command"]
    payload = json.dumps({"conversationId": "c1", "stepIdx": 7, "toolCall": {"name": "run_command"}})
    out = subprocess.run(["/bin/sh", "-c", command], input=payload, capture_output=True, text=True).stdout
    assert '"tool_use_id": "step-7"' in out and out.strip().endswith("{}")


def test_agy_activity_reads_the_stream():
    agy = Antigravity()
    tool = {"event": "step_update", "step_update": {"step_type": "tool", "state": "ACTIVE", "tool_name": "run_command",
                                                    "tool_info": {"parameters": {"CommandLine": "pytest -q"}}}}
    assert agy.activity(tool) == "run_command: pytest -q"
    assert agy.activity({"event": "result", "result": {}}) == "finished"
