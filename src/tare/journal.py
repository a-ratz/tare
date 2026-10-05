"""The run journal: everything a Cliff or Swap run did, one JSON line per event.

The dashboard derives its whole state from the run directory, and the journal is its spine:
phases, probe readings, original runs, tails started and finished, search steps, the report.
"""
import json
import threading
import time
from pathlib import Path


class Journal:
    def __init__(self, out: Path | None):
        self.path = out / "journal.jsonl" if out else None
        self._lock = threading.Lock()

    def __call__(self, event: str, **data):
        if not self.path:
            return
        line = json.dumps({"t": round(time.time(), 3), "event": event, **data}, ensure_ascii=False)
        with self._lock, self.path.open("a") as f:
            f.write(line + "\n")


def read(out: Path) -> list[dict]:
    path = out / "journal.jsonl"
    if not path.exists():
        return []
    events = []
    for line in path.read_text().splitlines():
        try:
            events.append(json.loads(line))
        except ValueError:
            continue  # a line being written
    return events
