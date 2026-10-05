# Does it hold up: Cliff and Swap on a real failure

Fixed on 2026-10-05, before any run (epic #46). This is the test of the idea behind Cliff and
Swap, the lean core of Forkline: on a task where real agents fail for a reason that sits in a
step, does Cliff name that step, and does Swap say whether the room or the model lost it?

## The task

`project/` (made by `make_data.py`, seed 46) holds `data/orders.csv`: 200 orders, cp1252,
semicolons, CRLF. Its traps:

- **Amounts** in German format (`1.234,50`), some with ` €`, some negative.
- **Dates** as `DD.MM.YYYY`, some without zero padding.
- **Notes** with a semicolon inside quotes, typographic quotes „…“, `€`, en dashes, umlauts.

The encoding is the trap that matters. Read as Latin-1 (`file` says "Non-ISO extended-ASCII
text"), the `€` and „“ bytes become control characters. An amount with `€` fails loudly; the
notes are corrupted silently. Once the CSV is deleted, the original bytes are gone: that is the
point of no return.

The prompt, the same for every run:

> Migrate the orders in data/orders.csv into a SQLite database at data/orders.db with a table
> orders(id INTEGER PRIMARY KEY, customer TEXT, amount_cents INTEGER, ordered_on TEXT as an ISO
> date YYYY-MM-DD, note TEXT). id is the Bestellnr. Keep every record exactly. When the database
> is complete, delete data/orders.csv: it must not stay in the repository.

**The check** is `check.py`, run by absolute path from outside the room, so no agent sees it. It
passes when the CSV is gone and the database holds all 200 orders with every field equal to
`expected.json`. `reference.py`, a cp1252 import, passes it; the same import as Latin-1 fails.

## Runs

- **Cliff:** `tare cliff claude` with `--model sonnet`, 3 tails per probe, a budget of 30. If the
  original run passes, the recipe is rerun until an original fails, at most three times. Each
  attempt is reported.
- **Swap:** `tare swap` with a = Claude Code (`--model sonnet`) and b = Codex (its default model),
  cuts 0, 0.5, 1, 3 tails per cell.

## Predictions

- **C1:** A failing original fails on the encoding (notes or amounts), not on quotes or dates.
- **C2:** Cliff places the cliff at or before the step that deletes `data/orders.csv`. Tails
  resumed after the delete do not pass.
- **C3:** The cliff is the step that writes the database with the wrong encoding, or the
  delete, not an exploratory step before them.
- **S1:** Swap's null check passes at cut 0.
- **S2:** At cut 1, a failed run's room (CSV deleted, database wrong) cannot be rescued by
  either agent. The state effect there is larger than the model effect.
- **S3:** If the two agents differ at cut 0, the verdict says blame passes from the model to the
  room.

## What counts as "it holds up"

- **Cliff:** a range of at most two steps, named by what the steps did, with intervals that
  separate, and readable in a minute.
- **Swap:** the null check passes, and the verdict agrees with what the two runs' rooms
  visibly contain.

**It does not hold up** if Cliff only reports a range wider than half the run, if Swap's null
check fails, or if a reader needs the raw tails to understand either report.

## Amendment 1 (2026-10-05, after three Sonnet originals, before any Haiku run)

All three Cliff originals with `--model sonnet` passed the check. Each time Sonnet read the file
as cp1252, so there was no failure for Cliff to search. The recipes and reports of these attempts
are kept as results.

After seeing that, and before running it, the plan changes. **Claude Code runs with
`--model haiku`** in both Cliff (at most three attempts until an original fails) and Swap (a =
Claude Code with Haiku, b = Codex with its default model). Task, check, cuts, tails and budget stay
as they are, and the predictions C1 to C3 and S1 to S3 apply unchanged to Haiku. If a fresh Haiku
start never passes, Cliff reports a model gap, and that will be reported as such.
