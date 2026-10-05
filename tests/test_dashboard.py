import json
import urllib.request
from pathlib import Path

from tare import dashboard, recipe
from tare.journal import Journal


def cliff_run(tmp_path):
    j = Journal(tmp_path)
    j("start", kind="cliff", task="t", check="c", project="/p", tails=3, budget=30,
      sides={"a": {"agent": "claude", "args": [], "dir": "."}})
    j("phase", phase="tails")
    j("original", side="a", passed=False, detail="check exit 1", steps=["start", "Bash ls", "Bash rm x"])
    for i, ok in enumerate([True, True]):
        j("tail", id=f"0000-{i}", status="running", step=0, agent_name="claude", kind="native", dir=f"tails/0000-{i}")
        j("tail", id=f"0000-{i}", status="passed" if ok else "failed", detail="d")
    j("tail", id="0002-0", status="running", step=2, agent_name="claude", kind="native", dir="tails/0002-0")
    (tmp_path / "tails" / "0002-0").mkdir(parents=True)
    (tmp_path / "tails" / "0002-0" / "stdout.jsonl").write_text(json.dumps(
        {"type": "assistant", "message": {"content": [{"type": "tool_use", "name": "Bash", "input": {"command": "pytest -q"}}]}}) + "\n")
    return tmp_path


def test_cliff_state_folds_the_journal_and_shows_what_running_tails_do(tmp_path):
    s = dashboard.state(cliff_run(tmp_path))
    assert s["kind"] == "cliff" and s["phase"] == "tails" and s["params"] == {"cuts": None, "tails": 3, "budget": 30}
    assert s["originals"]["a"]["steps"][2] == "Bash rm x"
    steps = {r["step"]: r for r in s["steps"]}
    assert steps[0]["passes"] == 2 and steps[0]["n"] == 2 and steps[0]["rate"] == 1.0
    assert steps[2]["running"] == 1 and steps[2]["rate"] is None
    running = [t for t in s["tails"] if t["status"] == "running"]
    assert running[0]["activity"] == "Bash: pytest -q"


def test_swap_state_fills_the_matrix_and_computes_effects_once_every_cell_has_a_result(tmp_path):
    j = Journal(tmp_path)
    j("start", kind="swap", task="t", check="c", project="/p", tails=1, cuts=[0],
      sides={"a": {"agent": "claude", "args": [], "dir": "a"}, "b": {"agent": "codex", "args": [], "dir": "b"}})
    j("plan", cuts=[{"fraction": 0, "steps": {"a": 0, "b": 0}}])
    for room in "ab":
        for agent in "ab":
            name = f"cut0/cell-room-{room}-agent-{agent}-0"
            j("tail", id=name, status="running", cut=0, room=room, agent=agent, kind="cell", agent_name="claude", dir=f"swap/{name}")
            j("tail", id=name, status="passed" if agent == "a" else "failed", detail="d")
    cut = dashboard.state(tmp_path)["cells"][0]
    assert cut["cells"]["aa"] == {"passes": 1, "n": 1, "running": 0}
    assert cut["model"][0] == 1.0 and cut["state"][0] == 0.0


def test_running_original_shows_capsules_so_far(tmp_path):
    j = Journal(tmp_path)
    j("start", kind="cliff", task="t", check="c", project="/p", tails=3, budget=30,
      sides={"a": {"agent": "codex", "args": [], "dir": "."}})
    (tmp_path / "store" / "capsules").mkdir(parents=True)
    for name in ("0000-start.tar", "0001-x.tar", "0002-y.tar"):
        (tmp_path / "store" / "capsules" / name).write_bytes(b"")
    (tmp_path / "original").mkdir()
    (tmp_path / "original" / "stdout.jsonl").write_text(json.dumps({"type": "item.started",
                                                                    "item": {"type": "command_execution", "command": "ls -la"}}) + "\n")
    original = dashboard.state(tmp_path)["originals"]["a"]
    assert original == {"running": True, "count": 2, "activity": "runs: ls -la"}


def test_server_serves_the_page_and_the_state(tmp_path):
    server, url = dashboard.serve(cliff_run(tmp_path))
    try:
        assert b"tare live" in urllib.request.urlopen(url).read()
        assert json.loads(urllib.request.urlopen(url + "state").read())["kind"] == "cliff"
    finally:
        server.shutdown()


def test_recipe_argv_drops_and_restores_out_before_the_passthrough():
    argv = ["cliff", "claude", "fix it", "--check", "pytest", "--out", "/runs/1", "--", "--model", "sonnet"]
    plain = recipe.without_out(argv)
    assert plain == ["cliff", "claude", "fix it", "--check", "pytest", "--", "--model", "sonnet"]
    assert recipe.with_out(plain, Path("/runs/2")) == ["cliff", "claude", "fix it", "--check", "pytest",
                                                       "--out", "/runs/2", "--", "--model", "sonnet"]
    assert recipe.without_out(["swap", "x", "--out=/r"]) == ["swap", "x"]


def test_project_digest_follows_content_and_skips_tooling(tmp_path):
    (tmp_path / "a.py").write_text("x = 1\n")
    first = recipe.project_digest(tmp_path)
    (tmp_path / ".venv").mkdir()
    (tmp_path / ".venv" / "lib.py").write_text("ignored")
    assert recipe.project_digest(tmp_path) == first
    (tmp_path / "a.py").write_text("x = 2\n")
    assert recipe.project_digest(tmp_path) != first


class Named:
    def __init__(self, name):
        self.name = name


class Binary:
    binary = Path("/bin/true")


def test_recipe_notes_what_changed_since(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    (project / "a.py").write_text("x = 1\n")
    out = tmp_path / "run"
    out.mkdir()
    r = recipe.write(out, ["cliff", "claude", "t", "--check", "c"], "cliff", project, "t", "c",
                     {"a": (Named("claude"), Binary(), [])}, {"tails": 3})
    assert recipe.read(out)["project_digest"] == r["project_digest"]
    assert recipe.drift(r, {}) == []
    (project / "a.py").write_text("x = 2\n")
    assert any("has changed" in note for note in recipe.drift(r, {}))


def test_calibrate_rates_carry_the_judge_scores_of_finished_tails(tmp_path):
    j = Journal(tmp_path)
    j("start", kind="calibrate", task="t", check="tare judge", project="/p", tails=3,
      sides={"a": {"agent": "claude", "args": [], "dir": "."}})
    for i, detail in enumerate(["check exit 0: score 70 (threshold 0): fine", "check exit 1: score 40 (threshold 50): bad"]):
        j("tail", id=f"a-{i}", status="running", side="a", agent="a", agent_name="claude", kind="fresh", dir=f"calibrate/a-{i}")
        j("tail", id=f"a-{i}", status="passed" if i == 0 else "failed", detail=detail)
    j("tail", id="a-2", status="running", side="a", agent="a", agent_name="claude", kind="fresh", dir="calibrate/a-2")
    rate = dashboard.state(tmp_path)["rates"]["a"]
    assert rate["scores"] == [70, 40] and rate["mean"] == 55 and rate["running"] == 1
