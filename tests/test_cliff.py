import json
import random
from pathlib import Path

from tare import capsule as caps
from tare.agents import Claude
from tare.cliff import Search, report, search, wilson


def test_wilson_matches_known_values():
    lo, hi = wilson(3, 3)
    assert round(lo, 2) == 0.44 and hi == 1.0
    lo, hi = wilson(0, 3)
    assert lo == 0.0 and round(hi, 2) == 0.56
    assert wilson(0, 0) == (0.0, 1.0)


def deterministic(cliff_at):
    """Tails pass before the cliff and fail from it on."""
    return lambda step, n: [step < cliff_at] * n


def test_search_finds_a_sharp_cliff_with_separated_intervals():
    s = search(deterministic(9), last=20, tails=3, budget=60)
    assert s.cliff == (8, 9)
    assert s.separated and not s.rebounds
    assert s.verdict == "The run became lost at step 9."
    assert s.spent <= 60


def test_search_stops_when_a_fresh_start_fails_too():
    s = search(lambda step, n: [False] * n, last=10, tails=3, budget=30)
    assert s.cliff is None and "model gap" in s.verdict
    assert list(s.results) == [0]


def test_search_calls_an_unlucky_run_unlucky():
    s = search(lambda step, n: [True] * n, last=10, tails=3, budget=30)
    assert s.cliff is None and "unlucky" in s.verdict


def test_search_reports_a_range_when_the_budget_runs_out():
    s = search(deterministic(9), last=40, tails=3, budget=9)
    assert s.exhausted
    assert s.cliff[1] - s.cliff[0] > 1
    assert "budget ran out" in s.verdict


def test_search_with_noise_still_brackets_the_cliff():
    rng = random.Random(7)
    probe = lambda step, n: [rng.random() < (0.9 if step < 6 else 0.1) for _ in range(n)]
    s = search(probe, last=12, tails=4, budget=80)
    assert s.cliff is not None
    assert s.cliff[0] <= 6 <= s.cliff[1] + 1


def test_report_says_when_a_step_after_the_cliff_passes_again():
    s = Search(results={0: [True] * 3, 2: [True] * 3, 3: [False] * 3, 5: [True] * 3, 8: [False] * 3},
               cliff=(2, 3), separated=True, rebounds=[5], spent=15, verdict="The run became lost at step 3.")
    steps = [caps.Capsule(i, None, Path("/nonexistent"), 0, 0, f"step {i}") for i in range(9)]
    s.cliff = (2, 4)  # not adjacent: the report does not open archives
    text = "\n".join(report(s, steps, 30))
    assert "monotone  no: steps 5 pass again after the cliff" in text


def write_run(tmp_path, entries, archives):
    out = tmp_path / "run"
    (out / "original").mkdir(parents=True)
    (out / "store" / "capsules").mkdir(parents=True)
    (out / "original" / "session.jsonl").write_text("\n".join(json.dumps(e) for e in entries) + "\n")
    for name, files in archives.items():
        work = tmp_path / f"w-{name}"
        work.mkdir()
        for path, text in files.items():
            (work / path).write_text(text)
        caps.archive(work, out / "store" / "capsules" / f"{name}.tar")
    return out


def use(tool_id, name="Bash", command="ls"):
    return {"type": "tool_use", "id": tool_id, "name": name, "input": {"command": command}}


def result(tool_id):
    return {"type": "tool_result", "tool_use_id": tool_id, "content": "ok"}


def test_capsules_follow_the_transcript_group_parallel_calls_and_share_archives(tmp_path):
    entries = [
        {"sessionId": "s1", "message": {"role": "user", "content": "do it"}},
        {"message": {"role": "assistant", "content": [use("t1", command="echo a > a.txt")]}},
        {"message": {"role": "user", "content": [result("t1")]}},
        {"message": {"role": "assistant", "content": [use("t2", "Read"), use("t3", "Read")]}},
        {"message": {"role": "user", "content": [result("t2")]}},
        {"message": {"role": "user", "content": [result("t3")]}},
        {"message": {"role": "assistant", "content": [use("t4", command="echo b > b.txt")]}},
        {"message": {"role": "user", "content": [result("t4")]}},
    ]
    archives = {"0000-start": {"x.txt": "x"}, "0001-t1": {"x.txt": "x", "a.txt": "a"},
                "0002-t2": {"x.txt": "x", "a.txt": "a"}, "0003-t3": {"x.txt": "x", "a.txt": "a"},
                "0004-sub9": {"x.txt": "x"},  # a subagent's call: not in the main transcript
                "0005-t4": {"x.txt": "x", "a.txt": "a", "b.txt": "b"}}
    out = write_run(tmp_path, entries, archives)
    steps = caps.capsules(out, Claude())
    assert [s.tool_use_id for s in steps] == [None, "t1", "t3", "t4"]
    assert [s.cut for s in steps] == [0, 3, 6, 8]
    assert steps[2].tool == "Read ls + Read ls"
    # step 2 (two reads) left the workspace as step 1 had it: one archive for both
    assert steps[2].archive == steps[1].archive
    assert caps.changed_files(steps[0].archive, steps[3].archive) == ["a.txt", "b.txt"]
    assert caps.session_id(out) == "s1"


def test_run_check_passes_on_exit_zero(tmp_path):
    assert caps.run_check("test -f ok", tmp_path) == (False, "check exit 1")
    (tmp_path / "ok").write_text("")
    assert caps.run_check("test -f ok", tmp_path) == (True, "check exit 0")


def test_report_names_the_cliff_step_and_its_changes(tmp_path):
    entries = [{"sessionId": "s1", "message": {"role": "user", "content": "go"}},
               {"message": {"role": "assistant", "content": [use("t1", command="echo 41 > notes.txt")]}},
               {"message": {"role": "user", "content": [result("t1")]}}]
    out = write_run(tmp_path, entries, {"0000-start": {"x": "x"}, "0001-t1": {"x": "x", "notes.txt": "41"}})
    steps = caps.capsules(out, Claude())
    s = search(deterministic(1), last=1, tails=3, budget=12)
    text = "\n".join(report(s, steps, 12))
    assert "The run became lost at step 1." in text
    assert "at step 1: Bash echo 41 > notes.txt" in text
    assert "changed   notes.txt" in text


def test_cliff_continues_by_handoff_when_the_agent_cannot_resume(tmp_path, monkeypatch):
    from tare import cliff as cliff_module
    from tare.trail import Trail

    class NoResume:
        name = "noresume"
        native_resume = False

        def trail(self, lines):
            return Trail()

    used = []
    (tmp_path / "w").mkdir()
    caps.archive(tmp_path / "w", tmp_path / "empty.tar")
    steps = [caps.Capsule(i, None, tmp_path / "empty.tar", 0, 0, f"step {i}") for i in range(3)]
    monkeypatch.setattr(caps, "record", lambda *a, **k: None)
    monkeypatch.setattr(caps, "run_check", lambda check, work: (False, "check exit 1"))
    monkeypatch.setattr(caps, "capsules", lambda out, agent: steps)
    monkeypatch.setattr(caps, "session_lines", lambda out: [])
    monkeypatch.setattr(caps, "run_tail", lambda *a, **k: used.append(("native", a[3].step)) or caps.Tail(a[3].step, True, ""))
    monkeypatch.setattr(caps, "run_handoff", lambda *a, **k: used.append(("handoff", a[3].step)) or caps.Tail(a[3].step, False, ""))
    cliff_module.cliff(NoResume(), None, tmp_path, "task", "check", tmp_path, tails=1, budget=4, jobs=1)
    assert ("native", 0) in used  # step 0 is a fresh start for every agent
    assert all(kind == "handoff" for kind, step in used if step > 0)


def test_search_samples_the_baseline_before_it_declares_a_model_gap():
    # a model that passes one fresh start in five: 0/3 is likely, but not a gap
    outcomes = iter([False] * 5 + [True] + [False] * 200)
    s = search(lambda step, n: [next(outcomes) if step == 0 else False for _ in range(n)], last=6, tails=3, budget=60)
    assert len(s.results[0]) >= 6 and s.rate(0) > 0
    assert "model gap" not in s.verdict


def test_search_declares_a_model_gap_only_when_its_bound_is_clear():
    s = search(lambda step, n: [False] * n, last=6, tails=3, budget=60)
    assert s.interval(0)[1] < 0.2 and "model gap" in s.verdict and "upper end of the baseline's 95% interval" in s.verdict
    short = search(lambda step, n: [False] * n, last=6, tails=3, budget=6)
    assert "budget ran out before a model gap was clear" in short.verdict
