"""Usage: the tokens and the cost of agent runs (epic Token and cost tracking).

Each adapter reads its agent's own stream after a run into one shape. `input` counts every
input token, cached ones included, and `cached` is the part read from a prompt cache. `cost_usd`
is what the agent itself reports, or None when it reports none. Sums keep count of the runs
whose cost is unknown, so a total never looks complete when it is not.
"""
import json
from dataclasses import asdict, dataclass


@dataclass
class Usage:
    input: int = 0
    cached: int = 0
    cache_write: int = 0
    output: int = 0
    reasoning: int = 0
    cost_usd: float | None = None
    model: str | None = None
    runs: int = 1
    unpriced: int = 0  # runs among `runs` whose cost is unknown

    def __post_init__(self):
        if self.runs == 1 and self.cost_usd is None and self.unpriced == 0:
            self.unpriced = 1

    def __add__(self, other: "Usage") -> "Usage":
        costs = [u.cost_usd for u in (self, other) if u.cost_usd is not None]
        return Usage(self.input + other.input, self.cached + other.cached, self.cache_write + other.cache_write,
                     self.output + other.output, self.reasoning + other.reasoning,
                     sum(costs) if costs else None, _same(self.model, other.model),
                     self.runs + other.runs, self.unpriced + other.unpriced)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict | None) -> "Usage | None":
        if not data:
            return None
        return cls(**{k: data[k] for k in cls.__dataclass_fields__ if k in data})


def _same(a: str | None, b: str | None) -> str | None:
    """The model of a sum: the one model if all parts name the same (or none), else None."""
    return a if b in (None, a) else b if a is None else None


def total(usages) -> "Usage | None":
    """The sum of several usages (dicts or Usage), or None when there are none."""
    result = None
    for u in usages:
        u = Usage.from_dict(u) if isinstance(u, dict) else u
        if u is not None:
            result = u if result is None else result + u
    return result


def _count(n: int) -> str:
    return f"{n / 1e6:.2f}M" if n >= 1e6 else f"{n / 1e3:.1f}k" if n >= 1e3 else str(n)


def describe(u: "Usage | None") -> str:
    """One line: runs, tokens in and out, and the cost as far as it is known."""
    if u is None:
        return "no usage recorded"
    runs = f"{u.runs} run{'s' if u.runs != 1 else ''}, "
    tokens = f"{_count(u.input)} in ({_count(u.cached)} cached), {_count(u.output)} out"
    if u.cost_usd is None:
        cost = "cost unknown"
    elif u.unpriced:
        priced = u.runs - u.unpriced
        cost = f"{money(u.cost_usd)} for {priced} run{'s' if priced != 1 else ''}, cost unknown for {u.unpriced}"
    else:
        cost = money(u.cost_usd)
    return f"{runs}{tokens}, {cost}"


def money(usd: float) -> str:
    return f"${usd:.3f}" if usd < 10 else f"${usd:.2f}"


def of_run(events: list[dict]) -> dict:
    """The usage of a run, from its journal: per side (original and tails), the check, and the total."""
    labels: dict[str, str] = {}
    owner: dict[str, str] = {}  # tail id -> side key, from the event that started it
    sides: dict[str, list] = {}
    check: list = []
    for e in events:
        kind = e.get("event")
        if kind == "start":
            labels = {k: " ".join([v.get("agent", "?"), *v.get("args", [])]) for k, v in (e.get("sides") or {}).items()}
        elif kind == "tail" and e.get("status") == "running":
            owner[e["id"]] = e.get("agent") or e.get("side") or "?"
        elif kind in ("original", "tail"):
            key = e.get("side") if kind == "original" else owner.get(e.get("id"), "?")
            sides.setdefault(key, []).append(e.get("usage"))
            check.append(e.get("check_usage"))
    per_side = {k: total(v) for k, v in sides.items()}
    checks = total(check)
    everything = total([*per_side.values(), checks])
    return {"sides": {k: {"label": labels.get(k, k), "usage": u.to_dict() if u else None} for k, u in per_side.items()},
            "check": checks.to_dict() if checks else None, "total": everything.to_dict() if everything else None}


def report(out) -> list[str]:
    """The usage lines that end a report. Also writes usage.json into the run directory."""
    from . import journal as journals
    summary = of_run(journals.read(out))
    (out / "usage.json").write_text(json.dumps(summary, indent=2) + "\n")
    if summary["total"] is None:
        return []
    rows = [f"{k} {s['label']}: {describe(Usage.from_dict(s['usage']))}" for k, s in sorted(summary["sides"].items())
            if s["usage"]]
    if summary["check"]:
        rows.append(f"check (the judge): {describe(Usage.from_dict(summary['check']))}")
    rows.append(f"total: {describe(Usage.from_dict(summary['total']))}")
    return ["", f"  usage     {rows[0]}", *[f"            {r}" for r in rows[1:]]]
