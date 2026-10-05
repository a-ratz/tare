"""Acceptance for Cliff: the real Claude Code CLI, rooms, resume and check, against a scripted
model whose cliff is known. Expected report: "The run became lost at step 4."

usage: uv run experiments/cliff-scripted/world.py [BUDGET]

The world: steps 1-3 are harmless, step 4 writes notes.txt with the answer, step 5 reads it,
step 6 writes answer.txt from it. At step 4 the model writes the wrong answer with
probability q. The original run is forced to (q = 1); tails use q = 0.1. Tails from step
0-3 reach step 4 afresh and mostly pass; tails from step 4 on read the poisoned note and
fail. Expected: the run became lost at step 4.
"""
import random
import sys
import tempfile
import threading
import uuid
from pathlib import Path

import tare.capsule as caps
from tare.agents import Claude
from tare.cliff import cliff
from tare.fake import Fake


class World:
    def __init__(self):
        self.q = 1.0
        self.rng = random.Random(4)
        self.lock = threading.Lock()

    def __call__(self, body):
        results = [b for m in body["messages"] if isinstance(m["content"], list)
                   for b in m["content"] if b.get("type") == "tool_result"]
        step = len(results)
        if step == 3:
            with self.lock:
                wrong = self.rng.random() < self.q
            command = f"echo answer={41 if wrong else 42} > notes.txt"
        elif step == 5:
            last = results[-1]["content"]
            text = last if isinstance(last, str) else " ".join(c.get("text", "") for c in last)
            command = f"echo {41 if 'answer=41' in text else 42} > answer.txt"
        elif step < 6:
            command = ["ls", "pwd", "echo hi > scratch.txt", None, "cat notes.txt"][step]
        else:
            return [{"type": "text", "text": "done"}]
        return [{"type": "tool_use", "id": f"toolu_{uuid.uuid4().hex[:12]}", "name": "Bash",
                 "input": {"command": command, "description": f"step {step + 1}"}}]


world = World()
original_record = caps.record


def record(*args, **kwargs):
    proc = original_record(*args, **kwargs)
    world.q = 0.1  # the original was forced; tails are honest most of the time
    return proc


caps.record = record
project = Path(tempfile.mkdtemp(prefix="cliff-project-"))
(project / "README.md").write_text("Write the answer to answer.txt.\n")
out = Path(tempfile.mkdtemp(prefix="cliff-e2e-")) / "run"
out.mkdir()
agent = Claude()
with Fake(world) as fake:
    text = cliff(agent, agent.discover(), project, "Write the answer to answer.txt.",
                 'test "$(cat answer.txt)" = 42', out, tails=3, budget=int(sys.argv[1]) if len(sys.argv) > 1 else 30,
                 jobs=3, env={"ANTHROPIC_BASE_URL": fake.url})
print(text)
print("run directory:", out)
