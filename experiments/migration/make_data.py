"""Generate the migration task: project/ (what the agent sees) and expected.json (what the check knows).

usage: uv run experiments/migration/make_data.py   (deterministic; seed 46)
"""
import json
import random
from pathlib import Path

HERE = Path(__file__).resolve().parent
rng = random.Random(46)
FIRST = ["Jürgen", "Zoë", "Björn", "Käthe", "Søren", "Renée", "Günther", "Maëlle", "Jörg", "Annegret", "Lukas", "Ida"]
LAST = ["Müller", "Weiß", "Öztürk", "Groß", "Schäfer", "Ångström", "Brühl", "Meyer", "Straßer", "Lindqvist", "Krüger", "Hoß"]
NOTES = ["", "", "", "", "Lieferung; bitte klingeln", "„Express“ gewünscht", "Rabatt 5 €", "Größe XL", "Geschenk – nicht öffnen",
         "Rückruf erbeten; Tel. hinterlegt", "„Abholung“ im Laden", "Gutschrift 12,50 €"]


def german_amount(cents: int, euro_sign: bool) -> str:
    sign = "-" if cents < 0 else ""
    euros, rest = divmod(abs(cents), 100)
    whole = f"{euros:,}".replace(",", ".")
    text = f"{sign}{whole},{rest:02d}"
    return text + (" €" if euro_sign else "")


rows, expected = [], []
for i in range(200):
    oid = 1001 + i
    customer = f"{rng.choice(FIRST)} {rng.choice(LAST)}"
    cents = rng.randint(50, 250_000) * (-1 if rng.random() < 0.08 else 1)
    day, month = rng.randint(1, 28), rng.randint(1, 12)
    date = f"{day}.{month}.2026" if rng.random() < 0.12 else f"{day:02d}.{month:02d}.2026"
    note = rng.choice(NOTES)
    amount = german_amount(cents, rng.random() < 0.15)
    quoted = f'"{note}"' if ";" in note or rng.random() < 0.3 else note
    rows.append(f"{oid};{customer};{amount};{date};{quoted}")
    expected.append({"id": oid, "customer": customer, "amount_cents": cents, "ordered_on": f"2026-{month:02d}-{day:02d}",
                     "note": note})

project = HERE / "project"
(project / "data").mkdir(parents=True, exist_ok=True)
(project / "data" / "orders.csv").write_bytes(("Bestellnr;Kunde;Betrag;Datum;Notiz\r\n" + "\r\n".join(rows) + "\r\n").encode("cp1252"))
(project / "README.md").write_text("# Shop orders\n\nThe order export of the old shop system lives in `data/orders.csv`.\n")
(HERE / "expected.json").write_text(json.dumps(expected, ensure_ascii=False, indent=1) + "\n")
print(f"{len(rows)} rows; total {sum(e['amount_cents'] for e in expected)} cents")
