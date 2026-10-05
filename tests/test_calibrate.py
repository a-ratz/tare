from pathlib import Path

import pytest

from tare import calibrate as cal
from tare import capsule as caps
from tare import dashboard
from tare.cli import main
from tare.journal import Journal


class Named:
    def __init__(self, name):
        self.name = name


def test_calibrate_reports_each_side_with_its_interval_and_journals_every_run(tmp_path, monkeypatch):
    project = tmp_path / "project"
    project.mkdir()
    (project / "README.md").write_text("x")
    out = tmp_path / "run"
    out.mkdir()
    outcomes = {"claude": iter([True, False, False, False]), "codex": iter([True] * 4)}

    def fake_tail(agent, real, out_, capsule, prompt, args, check, i, env=None, timeout=1800, tail_dir=None, keep=False):
        assert capsule.step == 0 and capsule.archive.exists()
        return caps.Tail(0, next(outcomes[agent.name]), "d")

    monkeypatch.setattr(caps, "run_tail", fake_tail)
    sides = [cal.Side("a", Named("claude"), None, ["--model", "haiku"]), cal.Side("b", Named("codex"), None, [])]
    text = cal.calibrate(sides, project, "task", "check", out, runs=4, jobs=2, journal=Journal(out))
    assert "a     claude --model haiku   1/4  0.25" in text
    assert "b     codex                  4/4  1.00" in text
    state = dashboard.state(out)
    assert state["kind"] == "calibrate" and state["phase"] == "done"
    assert state["rates"]["a"]["passes"] == 1 and state["rates"]["b"]["n"] == 4


def test_each_side_runs_its_own_prompt_and_without_a_check_every_run_is_kept(tmp_path, monkeypatch):
    project = tmp_path / "project"
    project.mkdir()
    (project / "README.md").write_text("x")
    out = tmp_path / "run"
    out.mkdir()
    seen = []

    def fake_tail(agent, real, out_, capsule, prompt, args, check, i, env=None, timeout=1800, tail_dir=None, keep=False):
        seen.append((agent.name, prompt, check, keep))
        return caps.Tail(0, True, "agent exit 0; no check")

    monkeypatch.setattr(caps, "run_tail", fake_tail)
    sides = [cal.Side("a", Named("claude"), None, [], "/unboring:ideate x"), cal.Side("b", Named("codex"), None, [])]
    text = cal.calibrate(sides, project, "shared task", None, out, runs=2, jobs=2, journal=Journal(out))
    assert sorted(set(seen)) == [("claude", "/unboring:ideate x", None, True), ("codex", "shared task", None, True)]
    assert "  task      shared task" in text and "  task a    /unboring:ideate x" in text
    assert "check     none" in text and "finished" in text and "   2/2" in text
    state = dashboard.state(out)
    assert state["check"] is None and state["sides"]["a"]["prompt"] == "/unboring:ideate x"
    assert len(state["rates"]["b"]["times"]) == 2


def test_without_a_check_a_run_counts_when_its_agent_ended_normally(tmp_path):
    work = tmp_path / "work"
    work.mkdir()
    tail = caps._finish(tmp_path, work, 0, "agent exit 0", None)
    assert tail.passed and tail.detail == "agent exit 0; no check"
    assert not caps._finish(tmp_path, work, 0, "agent stopped after 1800 s", None).passed


def test_side_prompts_must_name_a_side_and_every_side_needs_a_prompt():
    with pytest.raises(SystemExit):
        main(["calibrate", "task", "--side", "claude", "--side", "codex", "--side-prompt", "c=x"])
    with pytest.raises(SystemExit):
        main(["calibrate", "--side", "claude", "--side", "codex", "--side-prompt", "a=x"])


def test_the_report_ends_with_usage_per_side_the_judge_and_the_total(tmp_path, monkeypatch):
    project = tmp_path / "project"
    project.mkdir()
    (project / "README.md").write_text("x")
    out = tmp_path / "run"
    out.mkdir()

    def fake_tail(agent, real, out_, capsule, prompt, args, check, i, env=None, timeout=1800, tail_dir=None, keep=False):
        cost = 0.01 if agent.name == "claude" else None
        return caps.Tail(0, True, "check exit 0: score 70", {"input": 1000, "cached": 400, "output": 50, "cost_usd": cost},
                         {"input": 300, "output": 20, "cost_usd": 0.002})

    monkeypatch.setattr(caps, "run_tail", fake_tail)
    sides = [cal.Side("a", Named("claude"), None, []), cal.Side("b", Named("codex"), None, [])]
    text = cal.calibrate(sides, project, "task", "tare judge", out, runs=2, jobs=2, journal=Journal(out))
    assert "  usage     a claude: 2 runs, 2.0k in (800 cached), 100 out, $0.020" in text
    assert "            b codex: 2 runs, 2.0k in (800 cached), 100 out, cost unknown" in text
    assert "            check (the judge): 4 runs, 1.2k in (0 cached), 80 out, $0.008" in text
    assert "total: 8 runs" in text and (out / "usage.json").exists()
