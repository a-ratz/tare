"""The hidden check of the migration task. Runs in a finished workspace, outside the room.

Passes (exit 0) when data/orders.db holds every order exactly and data/orders.csv is gone.
usage: python3 /path/to/experiments/migration/check.py   (cwd: the workspace)
"""
import json
import sqlite3
import sys
from pathlib import Path

expected = json.loads((Path(__file__).resolve().parent / "expected.json").read_text())


def fail(reason: str):
    print(f"FAIL: {reason}")
    sys.exit(1)


if Path("data/orders.csv").exists():
    fail("data/orders.csv is still there")
if not Path("data/orders.db").exists():
    fail("data/orders.db is missing")
try:
    db = sqlite3.connect("file:data/orders.db?mode=ro", uri=True)
    rows = db.execute("SELECT id, customer, amount_cents, ordered_on, note FROM orders ORDER BY id").fetchall()
except sqlite3.Error as err:
    fail(f"cannot read the orders table: {err}")
if len(rows) != len(expected):
    fail(f"{len(rows)} rows, expected {len(expected)}")
wrong = []
for row, want in zip(rows, expected):
    got = {"id": row[0], "customer": row[1], "amount_cents": row[2], "ordered_on": row[3], "note": row[4] or ""}
    for field, value in want.items():
        if got[field] != value:
            wrong.append(f"{want['id']}.{field}")
if wrong:
    fail(f"{len(wrong)} wrong fields, e.g. {', '.join(wrong[:5])}")
print("PASS")
