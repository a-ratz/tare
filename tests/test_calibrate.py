from pathlib import Path

from tare import calibrate as cal
from tare import capsule as caps
from tare import dashboard
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
