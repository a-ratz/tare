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


def test_a_runs_output_reaches_its_files_through_pipes(tmp_path):
    """The agent's stdout is a pipe, never the run directory's file: a Node.js agent aborts at start
    when its stdout is a file in a place the room denies (#172)."""
    from tare.capsule import _stream
    code = _stream(["/bin/sh", "-c", '[ -p /dev/fd/1 ] && echo pipe; [ -p /dev/fd/2 ] && echo pipe >&2; exit 3'],
                   tmp_path, 30)
    assert code == 3
    assert (tmp_path / "stdout.jsonl").read_text() == "pipe\n"
    assert (tmp_path / "stderr.log").read_text() == "pipe\n"


def test_a_process_left_holding_the_pipe_does_not_hold_up_the_run(tmp_path, monkeypatch):
    import os
    import signal
    import time
    from tare import capsule
    monkeypatch.setattr(capsule, "PUMP_GRACE", 0.3)
    started = time.monotonic()
    script = f"echo done; (sleep 30; echo late) & echo $! > {tmp_path}/left.pid"
    assert capsule._stream(["/bin/sh", "-c", script], tmp_path, 30) == 0
    assert time.monotonic() - started < 10  # not the 30 seconds the left process holds the pipe
    assert (tmp_path / "stdout.jsonl").read_text().startswith("done\n")
    os.kill(int((tmp_path / "left.pid").read_text()), signal.SIGKILL)


def test_a_pump_that_cannot_write_drains_on_so_the_agent_never_blocks(tmp_path):
    import subprocess
    import threading
    from tare.capsule import _pump

    class Full:
        def write(self, chunk):
            raise OSError(28, "No space left on device")

        def flush(self):
            pass
    proc = subprocess.Popen(["/bin/sh", "-c", "head -c 300000 /dev/zero"], stdout=subprocess.PIPE)
    pump = threading.Thread(target=_pump, args=(proc.stdout, Full()), daemon=True)
    pump.start()
    assert proc.wait(timeout=10) == 0  # 300 KB through a 64 KB pipe: only a reader lets it finish
    pump.join(timeout=5)


ATTACHED = '''
import signal, sys
from tare.cli import _exit_on, _run_attached
signal.signal(signal.SIGTERM, _exit_on)  # as tare's main installs it
sys.exit(_run_attached(sys.argv[1:]))
'''


def attached(tmp_path, argv, stdin=None):
    """tare's attached run in a process of its own, its stdout and stderr files, as `tare pi -- ... > out`."""
    import subprocess
    import sys
    out, err = (tmp_path / "out").open("w"), (tmp_path / "err").open("w")
    return subprocess.Popen([sys.executable, "-c", ATTACHED, *argv], stdin=stdin, stdout=out, stderr=err)


def test_an_attached_run_redirected_to_files_hands_the_agent_pipes_and_its_exit(tmp_path):
    script = 'for fd in 0 1 2; do [ -p /dev/fd/$fd ] && echo "$fd pipe" >&2; done; cat; echo out; exit 4'
    (tmp_path / "in").write_text("from a file\n")
    with (tmp_path / "in").open() as stdin:
        proc = attached(tmp_path, ["/bin/sh", "-c", script], stdin=stdin)
        assert proc.wait(timeout=30) == 4
    assert (tmp_path / "out").read_text() == "from a file\nout\n"
    assert (tmp_path / "err").read_text() == "0 pipe\n1 pipe\n2 pipe\n"


def test_a_signal_ends_the_agent_of_an_attached_run_before_its_room_goes(tmp_path):
    import os
    import signal
    import time
    proc = attached(tmp_path, ["/bin/sh", "-c", f"echo $$ > {tmp_path}/agent.pid; exec sleep 30"])
    for _ in range(100):
        if (tmp_path / "agent.pid").exists() and (tmp_path / "agent.pid").read_text().strip():
            break
        time.sleep(0.05)
    agent = int((tmp_path / "agent.pid").read_text())
    proc.send_signal(signal.SIGTERM)
    assert proc.wait(timeout=10) == 128 + signal.SIGTERM
    try:
        os.kill(agent, 0)
    except ProcessLookupError:
        return
    os.kill(agent, signal.SIGKILL)
    pytest.fail("the agent outlived tare")
