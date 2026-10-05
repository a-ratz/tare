"""Acceptance for Swap: the real Claude Code CLI, rooms, capsules, handoffs, native resume and
check, against two scripted models whose truth is known.

usage: uv run experiments/swap-scripted/world.py [TAILS]

The task is to write 42 to answer.txt. Model a is competent but trusts notes.txt; model b is
weak: it ignores the notes and writes 42 or 41 with even odds. Run a writes a true note
(answer=42) at step 2, run b a poisoned one (answer=41). Expected:
- cut 0: both rooms are the untouched project: state effect 0 (null check), model effect +0.5;
- cuts 0.5 and 1: room b misleads agent a: state effect +0.5, model effect 0;
- verdict: blame passes from the model to the room between cut 0.00 and cut 0.50.
"""
import random
import sys
import tempfile
import threading
import uuid
from pathlib import Path

import tare.capsule as caps
from tare.agents import Claude
from tare.fake import Fake
from tare.swap import Side, swap


def tool_calls(body):
    return [b for m in body["messages"] if m["role"] == "assistant" and isinstance(m["content"], list)
            for b in m["content"] if b.get("type") == "tool_use"]


def results(body):
    return [b for m in body["messages"] if isinstance(m["content"], list)
            for b in m["content"] if b.get("type") == "tool_result"]


def text_of(result):
    content = result["content"]
    return content if isinstance(content, str) else " ".join(c.get("text", "") for c in content)


def bash(command):
    return [{"type": "tool_use", "id": f"toolu_{uuid.uuid4().hex[:12]}", "name": "Bash",
             "input": {"command": command, "description": command[:30]}}]


DONE = [{"type": "text", "text": "done"}]


class World:
    def __init__(self):
        self.phase = "original"
        self.recorded = 0
        self.rng = random.Random(17)
        self.lock = threading.Lock()

    def __call__(self, body):
        model = body.get("model", "")
        side = "a" if "opus" in model else "b"
        calls, done = tool_calls(body), results(body)
        last = calls[-1]["input"]["command"] if calls else ""
        if self.phase == "original":
            note = "answer=42" if side == "a" else "answer=41"
            script = ["ls", f"echo {note} > notes.txt", "cat notes.txt", None]
            if len(done) < 3:
                return bash(script[len(done)])
            if len(done) == 3:
                return bash(f"echo {41 if 'answer=41' in text_of(done[-1]) else 42} > answer.txt")
            return DONE
        if "answer.txt" in last and calls and len(done) == len(calls):
            return DONE
        if side == "a":
            if last.startswith("cat notes.txt") and len(done) == len(calls):
                return bash(f"echo {41 if 'answer=41' in text_of(done[-1]) else 42} > answer.txt")
            return bash("cat notes.txt 2>/dev/null || echo none")
        with self.lock:
            guess = 42 if self.rng.random() < 0.5 else 41
        return bash(f"echo {guess} > answer.txt")


world = World()
original_record = caps.record


def record(*args, **kwargs):
    proc = original_record(*args, **kwargs)
    with world.lock:
        world.recorded += 1
        if world.recorded == 2:
            world.phase = "tails"
    return proc


caps.record = record
project = Path(tempfile.mkdtemp(prefix="swap-project-"))
(project / "README.md").write_text("Write the answer to answer.txt.\n")
out = Path(tempfile.mkdtemp(prefix="swap-e2e-"))
claude = Claude()
real = claude.discover()
a = Side("a", claude, real, ["--model", "claude-opus-5-5"], out / "a")
b = Side("b", claude, real, ["--model", "claude-haiku-4-5-20251001"], out / "b")
tails = int(sys.argv[1]) if len(sys.argv) > 1 else 4
with Fake(world) as fake:
    print(swap(a, b, project, "Write the answer to answer.txt.", 'test "$(cat answer.txt)" = 42', out,
               cuts=[0, 0.5, 1], tails=tails, jobs=4, env={"ANTHROPIC_BASE_URL": fake.url}))
print("run directory:", out)
