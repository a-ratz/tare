"""A correct migration, to prove the task is solvable and the check can pass.

usage: uv run --no-project python3 /path/to/experiments/migration/reference.py   (cwd: a copy of project/)
"""
import csv
import io
import sqlite3
from pathlib import Path

rows = list(csv.reader(io.StringIO(Path("data/orders.csv").read_bytes().decode("cp1252")), delimiter=";"))[1:]
db = sqlite3.connect("data/orders.db")
db.execute("CREATE TABLE orders(id INTEGER PRIMARY KEY, customer TEXT, amount_cents INTEGER, ordered_on TEXT, note TEXT)")
for oid, customer, amount, date, note in rows:
    digits = amount.replace("€", "").strip().replace(".", "").replace(",", "")
    day, month, year = date.split(".")
    db.execute("INSERT INTO orders VALUES (?, ?, ?, ?, ?)",
               (int(oid), customer, int(digits), f"{year}-{int(month):02d}-{int(day):02d}", note))
db.commit()
Path("data/orders.csv").unlink()
