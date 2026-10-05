import json
from pathlib import Path

from tare import trail
from tare.swap import Cut, Side, mean_effect, newcombe, report


def jl(*entries):
    return [json.dumps(e) for e in entries]


def test_claude_transcript_becomes_a_trail_with_steps():
    lines = jl(
        {"sessionId": "s", "message": {"role": "user", "content": "do it"}},
        {"message": {"role": "assistant", "content": [{"type": "text", "text": "Looking."},
                                                      {"type": "tool_use", "id": "t1", "name": "Bash", "input": {"command": "ls"}}]}},
        {"message": {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "t1", "content": "a.txt"}]}},
        {"message": {"role": "assistant", "content": [{"type": "text", "text": "Done."}]}},
    )
    t = trail.claude(lines)
    assert [(e.kind, e.text) for e in t.events] == [("say", "Looking."), ("call", "ls"), ("result", "a.txt"), ("say", "Done.")]
    assert len(t.steps) == 1 and t.steps[0].ids == ["t1"] and t.steps[0].trail_cut == 3 and t.steps[0].native_cut == 3


def test_codex_rollout_becomes_a_trail_and_a_step_carries_its_inner_commands():
    lines = jl(
        {"type": "session_meta", "payload": {"id": "s"}},
        {"type": "response_item", "payload": {"type": "message", "role": "user", "content": [{"type": "input_text", "text": "task"}]}},
        {"type": "response_item", "payload": {"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": "On it."}]}},
        {"type": "response_item", "payload": {"type": "custom_tool_call", "call_id": "call_1", "name": "exec",
                                               "input": "text(await tools.exec_command({cmd:'ls'}))"}},
        {"type": "event_msg", "payload": {"type": "item_completed", "item": {"type": "CommandExecution", "id": "exec-1"}}},
        {"type": "event_msg", "payload": {"type": "item_completed", "item": {"type": "CommandExecution", "id": "exec-2"}}},
        {"type": "response_item", "payload": {"type": "custom_tool_call_output", "call_id": "call_1",
                                               "output": [{"type": "input_text", "text": "a.txt"}]}},
    )
    t = trail.codex(lines)
    assert [e.kind for e in t.events] == ["say", "call", "result"]
    assert t.events[1].tool == "exec" and t.events[2].text == "a.txt"
    assert t.steps[0].ids == ["call_1", "exec-1", "exec-2"]
    assert t.steps[0].trail_cut == 3 and t.steps[0].native_cut == 7


def test_handoff_renders_the_task_and_the_trail_the_same_for_every_agent():
    events = [trail.Event("say", "Looking."), trail.Event("call", "ls", "Bash"), trail.Event("result", "a.txt")]
    text = trail.render("Write the answer.", events)
    assert "The task:\nWrite the answer." in text
    assert "1. The agent said: Looking." in text and "2. The agent called Bash: ls" in text and "3. Result: a.txt" in text
    assert "What happened so far" not in trail.render("Write the answer.", events, workspace_only=True)
    assert "What happened so far" not in trail.render("Write the answer.", [])


def test_long_tool_output_is_shortened_in_the_trail():
    lines = jl({"message": {"role": "assistant", "content": [{"type": "tool_use", "id": "t1", "name": "Bash", "input": {"command": "cat big"}}]}},
               {"message": {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "t1", "content": "x" * 5000}]}})
    result = trail.claude(lines).events[1].text
    assert len(result) < 700 and "more characters" in result


def test_newcombe_difference_has_the_known_shape():
    d, lo, hi = newcombe(3, 3, 0, 3)
    assert d == 1.0 and 0.2 < lo < 0.6 and hi == 1.0
    d, lo, hi = newcombe(2, 4, 2, 4)
    assert d == 0.0 and lo < 0 < hi


def test_mean_effect_averages_and_narrows():
    e, lo, hi = mean_effect([(1.0, 0.4, 1.0), (0.0, -0.5, 0.5)])
    assert e == 0.5 and lo < 0.5 < hi


def cut(fraction, rates, native=None, n=4):
    c = Cut(fraction, {"a": 0, "b": 0})
    for (room, agent), passes in rates.items():
        c.cells[(room, agent)] = [True] * passes + [False] * (n - passes)
    for side, passes in (native or {}).items():
        c.native[side] = [True] * passes + [False] * (n - passes)
    return c


def test_state_and_model_effects_separate_room_from_model():
    # agent a is better everywhere, the rooms do not matter
    model_only = cut(0, {("a", "a"): 4, ("a", "b"): 1, ("b", "a"): 4, ("b", "b"): 1})
    assert model_only.model()[0] == 0.75 and model_only.state()[0] == 0
    # room b is damaged for both agents
    room_only = cut(1, {("a", "a"): 4, ("a", "b"): 4, ("b", "a"): 0, ("b", "b"): 0})
    assert room_only.state()[0] == 1.0 and room_only.model()[0] == 0


def test_foreignness_compares_native_resume_with_the_handoff_on_the_own_room():
    c = cut(0.5, {("a", "a"): 2, ("a", "b"): 2, ("b", "a"): 2, ("b", "b"): 2}, native={"a": 4})
    assert c.foreignness("a")[0] == 0.5
    assert c.foreignness("b") is None


class Named:
    def __init__(self, name):
        self.name = name


def test_report_names_the_transfer_and_the_null_check():
    sides = {"a": Side("a", Named("claude"), None, ["--model", "x"], Path("/a"), original="passed"),
             "b": Side("b", Named("codex"), None, [], Path("/b"), original="failed")}
    plan = [cut(0.0, {("a", "a"): 4, ("a", "b"): 1, ("b", "a"): 4, ("b", "b"): 1}),
            cut(1.0, {("a", "a"): 4, ("a", "b"): 4, ("b", "a"): 0, ("b", "b"): 0})]
    text = "\n".join(report(sides, plan, "task", "check", Path("/p"), 32, False))
    assert "a: claude --model x · b: codex" in text
    assert "null check   passed" in text
    assert "blame passes from the model to the room between cut 0.00 and cut 1.00" in text


def test_report_fails_the_null_check_when_identical_rooms_differ():
    sides = {"a": Side("a", Named("claude"), None, [], Path("/a")), "b": Side("b", Named("codex"), None, [], Path("/b"))}
    plan = [cut(0.0, {("a", "a"): 4, ("a", "b"): 4, ("b", "a"): 0, ("b", "b"): 0}, n=8)]
    assert "null check   FAILED" in "\n".join(report(sides, plan, "t", "c", Path("/p"), 16, False))


def test_report_says_neither_when_no_effect_shows():
    sides = {"a": Side("a", Named("claude"), None, [], Path("/a")), "b": Side("b", Named("codex"), None, [], Path("/b"))}
    plan = [cut(0.0, {k: 4 for k in [("a", "a"), ("a", "b"), ("b", "a"), ("b", "b")]}),
            cut(1.0, {k: 4 for k in [("a", "a"), ("a", "b"), ("b", "a"), ("b", "b")]})]
    assert "neither the room nor the model makes a difference at any cut" in "\n".join(
        report(sides, plan, "t", "c", Path("/p"), 32, False))
