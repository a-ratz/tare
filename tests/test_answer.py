"""The answer at the top of a run page: its sentence per verdict, figures and trust line (epic #138)."""
from tare.answer import act, answer, judged, names
from tare.cliff import wilson

CLAUDE = {"agent": "claude", "args": ["--model", "haiku"]}
CODEX = {"agent": "codex", "args": ["-m", "gpt-6.1-sol"]}


def rate(passes, n, scores=(), times=(), running=0):
    lo, hi = wilson(passes, n)
    return {"passes": passes, "n": n, "running": running, "rate": passes / n if n else None, "lo": lo, "hi": hi,
            "scores": list(scores), "mean": sum(scores) / len(scores) if scores else None, "times": list(times)}


def state(kind, sides, phase="done", **rest):
    return {"kind": kind, "sides": sides, "phase": phase, "probes": [], "params": rest.pop("params", {}),
            "originals": rest.pop("originals", {}), "check": rest.pop("check", "c"), **rest}


def test_names_add_the_model_only_when_two_sides_share_an_agent():
    assert names({"a": CLAUDE, "b": CODEX})["a"]["full"] == "Claude Code"
    shared = names({"a": CLAUDE, "b": {"agent": "claude", "args": ["--model", "sonnet"]}})
    assert (shared["a"]["full"], shared["b"]["full"]) == ("Claude Code with haiku", "Claude Code with sonnet")
    assert shared["a"]["label"] == "Claude Code · haiku"


def test_judge_detail_gives_score_threshold_and_reason():
    assert judged("agent exit 0; check exit 0: score 68 (threshold 0): Both charts render.") == \
        {"score": 68, "threshold": 0, "reason": "Both charts render."}
    assert judged("check exit 1") is None


def test_calibrate_with_judge_scores_names_the_higher_scorer():
    s = state("calibrate", {"a": CLAUDE, "b": CODEX}, params={"tails": 5},
              rates={"a": rate(5, 5, [38, 66, 76, 80, 80]), "b": rate(5, 5, [10, 12, 14, 15, 22])})
    a = answer(s)
    assert a["sentence"] == "Claude Code scored higher: 68 against 15 out of 100, on average."
    assert "every Claude Code run scored above every Codex run" in a["detail"]
    assert [f["value"] for f in a["figures"]] == ["68", "15", "10"]
    assert {"cell": "limit", "text": "5 runs per agent: each pass rate is likely between 57% and 100%"} in a["trust"]


def test_calibrate_pass_or_fail_and_a_live_run():
    s = state("calibrate", {"a": CLAUDE, "b": CODEX}, params={"tails": 4}, rates={"a": rate(0, 4), "b": rate(4, 4)})
    assert answer(s)["sentence"] == "Codex passed 4 of 4 runs, Claude Code 0 of 4."
    live = answer({**s, "phase": "runs", "rates": {"a": rate(0, 2, running=1), "b": rate(2, 2, running=1)}})
    assert live["sentence"].startswith("So far: Codex passes 2 of 2 runs")
    assert {"cell": "running", "text": "4 of 8 runs done"} in live["trust"]


def test_calibrate_without_a_check_reports_times():
    s = state("calibrate", {"a": CLAUDE, "b": CODEX}, check=None, params={"tails": 2},
              rates={"a": rate(2, 2, times=[90, 94]), "b": rate(2, 2, times=[180, 200])})
    assert answer(s)["sentence"] == "Both agents finished every run. Claude Code took 1m 32s and Codex took 3m 10s on average."


def cut(fraction, cells, state, model, native=None):
    return {"fraction": fraction, "steps": {"a": 0, "b": 0}, "state": state, "model": model, "native": native or {},
            "cells": {k: {"passes": p, "n": 3, "running": 0} for k, p in cells.items()}}


def test_swap_sentence_follows_who_decided_at_each_handover_point():
    agent_wins = {"aa": 0, "ab": 3, "ba": 1, "bb": 3}
    s = state("swap", {"a": CLAUDE, "b": CODEX}, params={"tails": 3},
              cells=[cut(0, agent_wins, (-0.17, -0.53, 0.25), (-0.83, -0.97, -0.3)),
                     cut(0.5, agent_wins, (-0.17, -0.53, 0.25), (-0.83, -0.97, -0.3)),
                     cut(1, {"aa": 0, "ab": 3, "ba": 3, "bb": 3}, (-0.5, -0.78, -0.01), (-0.5, -0.78, -0.01))],
              originals={"a": {"passed": False}, "b": {"passed": True}})
    a = answer(s)
    assert a["sentence"] == "The agent decided until halfway. At the end, workspace and agent weighed about the same."
    assert "swapped their unfinished work at the start, halfway and at the end" in a["detail"]
    assert a["figures"][0] == {"value": "83", "unit": "points", "label": ["Codex ahead in the same", "workspaces at the start"]}
    only_agent = {**s, "cells": s["cells"][:2]}
    assert answer(only_agent)["sentence"] == "The agent decided, not the workspace: Codex passed more often in either workspace."


def cliff_state(rows, steps, phase="done", passed=False):
    def row(step, passes, n):
        lo, hi = wilson(passes, n)
        return {"step": step, "passes": passes, "n": n, "running": 0, "rate": passes / n, "lo": lo, "hi": hi}
    return state("cliff", {"a": CLAUDE}, phase=phase, params={"tails": 3, "budget": 30},
                 steps=[row(*r) for r in rows], originals={"a": {"passed": passed, "steps": steps}})


STEPS = ["start", "Bash ls", "Bash pwd", "Bash echo hi > scratch.txt", "Bash echo answer=41 > notes.txt",
         "Bash cat notes.txt", "Bash echo 41 > answer.txt"]


def test_cliff_names_the_step_and_what_the_agent_did():
    a = answer(cliff_state([(0, 3, 3), (3, 5, 6), (4, 0, 6), (6, 0, 3)], STEPS))
    assert a["sentence"] == "The run went wrong at step 4, when the agent ran `echo answer=41 > notes.txt`."
    assert [f["value"] for f in a["figures"]] == ["Step 4", "83%", "0%"]
    assert {"cell": "ok", "text": "No step after 4 passes again"} in a["trust"]
    assert {"cell": "ok", "text": "Likely ranges do not overlap: 44–97% before, 0–39% after"} in a["trust"]


def test_cliff_too_hard_unlucky_passed_and_still_searching():
    assert answer(cliff_state([(0, 0, 16)], STEPS))["sentence"] == \
        "The task is too hard for Claude Code: even a fresh start passes 0 of 16 times."  # 0 of 16: likely below 20%
    assert answer(cliff_state([(0, 0, 3)], STEPS))["sentence"].startswith("The task looks too hard for Claude Code")
    assert answer(cliff_state([(0, 1, 9), (6, 2, 3)], STEPS))["sentence"] == \
        "The run was unlucky, not lost: restarted at its last step, it still passes 2 of 3 times."
    assert answer(cliff_state([], STEPS, passed=True))["sentence"] == "The run passed, so no step lost it."
    assert answer(cliff_state([(0, 3, 3)], STEPS, phase="tails"))["sentence"] == \
        "Still searching. So far, a fresh start passes 3 of 3 times."


def test_act_turns_a_step_into_what_the_agent_did():
    assert act("Write /work/index.html") == "wrote index.html"
    assert act("Bash ls + Bash rm x") == "ran `rm x`"
    assert act("WebFetch https://example.com") == "made a WebFetch call"


def test_a_room_that_was_not_clean_heads_the_trust_line():
    s = state("calibrate", {"a": CLAUDE}, params={"tails": 1}, rates={"a": rate(1, 1)},
              probes=[{"agent": "claude", "zero": False, "text": "tare: 2 leaks"}])
    assert answer(s)["trust"][0] == {"cell": "failed", "text": "Claude Code: room not clean, run with --allow-dirty"}
