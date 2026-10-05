"""Usage: the tokens and the cost of agent runs (epic Token and cost tracking).

Each adapter reads its agent's own stream after a run into one shape. `input` counts every
input token, cached ones included, and `cached` is the part read from a prompt cache. `cost_usd`
is what the agent itself reports, or None when it reports none. Sums keep count of the runs
whose cost is unknown, so a total never looks complete when it is not.

Where an agent reports no cost, tare estimates it from a price table: LiteLLM's public table,
fetched on demand with `tare prices update`, and a file of the user's own that overrides single
models. An estimate always names its source and date.
"""
import json
import os
import re
import time
import urllib.request
from dataclasses import asdict, dataclass
from pathlib import Path

LITELLM_URL = "https://raw.githubusercontent.com/BerriAI/litellm/main/model_prices_and_context_window.json"
# where a model is listed under several prefixes, the maker's own price comes before resellers'
FIRST_PARTY = ("openai", "anthropic", "gemini", "zai", "xai", "mistral", "deepseek", "moonshot", "dashscope")


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
    estimated: str | None = None  # the price table behind an estimated cost, None for a reported one

    def __post_init__(self):
        if self.runs == 1 and self.cost_usd is None and self.unpriced == 0:
            self.unpriced = 1

    def __add__(self, other: "Usage") -> "Usage":
        costs = [u.cost_usd for u in (self, other) if u.cost_usd is not None]
        return Usage(self.input + other.input, self.cached + other.cached, self.cache_write + other.cache_write,
                     self.output + other.output, self.reasoning + other.reasoning,
                     sum(costs) if costs else None, _same(self.model, other.model),
                     self.runs + other.runs, self.unpriced + other.unpriced,
                     _same(self.estimated, other.estimated) if self.estimated and other.estimated
                     else self.estimated or other.estimated)

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


def billing(agent, real) -> str | None:
    """How a side's login pays ("subscription" or "api key"), where the adapter can tell."""
    try:
        return agent.billing(real) if real is not None and hasattr(agent, "billing") else None
    except Exception:
        return None


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
    elif u.estimated:
        cost = f"about {money(u.cost_usd)} (estimated from {u.estimated})"
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
    info: dict[str, dict] = {}
    owner: dict[str, str] = {}  # tail id -> side key, from the event that started it
    sides: dict[str, list] = {}
    check: list = []
    for e in events:
        kind = e.get("event")
        if kind == "start":
            info = e.get("sides") or {}
            labels = {k: " ".join([v.get("agent", "?"), *v.get("args", [])]) for k, v in info.items()}
        elif kind == "tail" and e.get("status") == "running":
            owner[e["id"]] = e.get("agent") or e.get("side") or "?"
        elif kind in ("original", "tail"):
            key = e.get("side") if kind == "original" else owner.get(e.get("id"), "?")
            sides.setdefault(key, []).append(e.get("usage"))
            check.append(e.get("check_usage"))
    per_side = {}
    for k, v in sides.items():
        side = info.get(k) or {}
        found = total(v)
        per_side[k] = found and estimate(found, model_from_args(side.get("args") or []),
                                         reasoning_extra=side.get("agent") == "agy")
    checks = total(check)
    everything = total([*per_side.values(), checks])
    return {"sides": {k: {"label": labels.get(k, k), "usage": u.to_dict() if u else None,
                          "billing": (info.get(k) or {}).get("billing")} for k, u in per_side.items()},
            "check": checks.to_dict() if checks else None, "total": everything.to_dict() if everything else None}


def report(out) -> list[str]:
    """The usage lines that end a report. Also writes usage.json into the run directory."""
    from . import journal as journals
    summary = of_run(journals.read(out))
    (out / "usage.json").write_text(json.dumps(summary, indent=2) + "\n")
    if summary["total"] is None:
        return []
    rows = [f"{k} {s['label']}: {describe(Usage.from_dict(s['usage']))}"
            + (". Subscription login, so the cost is notional" if s.get("billing") == "subscription" else "")
            for k, s in sorted(summary["sides"].items()) if s["usage"]]
    if summary["check"]:
        rows.append(f"check (the judge): {describe(Usage.from_dict(summary['check']))}")
    rows.append(f"total: {describe(Usage.from_dict(summary['total']))}")
    return ["", f"  usage     {rows[0]}", *[f"            {r}" for r in rows[1:]]]


# --- prices -----------------------------------------------------------------------------------

def config_dir() -> Path:
    return Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "tare"


def update_prices(url: str = LITELLM_URL) -> str:
    """Fetch LiteLLM's public price table into the config directory. Returns a one-line summary."""
    with urllib.request.urlopen(url, timeout=60) as r:
        models = json.loads(r.read())
    fetched = time.strftime("%Y-%m-%d")
    config_dir().mkdir(parents=True, exist_ok=True)
    (config_dir() / "prices-litellm.json").write_text(json.dumps({"source": url, "fetched": fetched, "models": models}))
    return f"{len(models)} models from LiteLLM, fetched {fetched}"


def _tables() -> list[tuple[str, dict]]:
    """(label, {model: per-token prices}) for the user's own file, then LiteLLM's table."""
    tables = []
    own = config_dir() / "prices.json"
    if own.exists():
        data = json.loads(own.read_text())
        per_million = {m: {k: v / 1e6 for k, v in p.items()} for m, p in (data.get("models") or {}).items()}
        tables.append((f"{own.name} ({data.get('source', 'no source given')}, {data.get('date', 'no date given')})",
                       per_million))
    litellm = config_dir() / "prices-litellm.json"
    if litellm.exists():
        data = json.loads(litellm.read_text())
        models = {m: {"input": p.get("input_cost_per_token"), "cached_input": p.get("cache_read_input_token_cost"),
                      "cache_write": p.get("cache_creation_input_token_cost"), "output": p.get("output_cost_per_token")}
                  for m, p in (data.get("models") or {}).items() if isinstance(p, dict) and p.get("input_cost_per_token")}
        tables.append((f"LiteLLM prices fetched {data.get('fetched')}", models))
    return tables


def tables_summary() -> list[str]:
    return [f"{label}: {len(table)} models" for label, table in _tables()]


def price_of(model: str | None) -> tuple[dict, str] | None:
    """The per-token prices of a model and the table they come from, or None. Tries the name as it
    is, then without an effort suffix (-high, -low ...), then under a provider prefix (zai/glm-5.3)."""
    if not model:
        return None
    names = [model, re.sub(r"-(minimal|low|medium|high|xhigh|max)$", "", model)]
    for label, table in _tables():
        for name in names:
            if name in table:
                return table[name], label
            prefixed = sorted((k for k in table if k.endswith("/" + name) and k.count("/") == 1),
                              key=lambda k: (FIRST_PARTY.index(k.split("/")[0]) if k.split("/")[0] in FIRST_PARTY
                                             else len(FIRST_PARTY), k))
            if prefixed:
                return table[prefixed[0]], label
    return None


def estimate(u: Usage, model: str | None, reasoning_extra: bool = False) -> Usage:
    """Fill in the cost of a usage whose runs all lack one, from the price table. `reasoning_extra`
    is for agents whose output count leaves out the reasoning tokens that are billed as output."""
    if u.cost_usd is not None or u.unpriced != u.runs:
        return u
    found = price_of(model or u.model)
    if not found:
        return u
    p, label = found
    fresh = max(0, u.input - u.cached - u.cache_write)
    output = u.output + (u.reasoning if reasoning_extra else 0)
    cost = (fresh * (p.get("input") or 0) + u.cached * (p.get("cached_input") or p.get("input") or 0)
            + u.cache_write * (p.get("cache_write") or p.get("input") or 0) + output * (p.get("output") or 0))
    return Usage(**{**u.to_dict(), "cost_usd": cost, "unpriced": 0, "estimated": label})


def model_from_args(args: list[str]) -> str | None:
    """The model a side pins with -m or --model, if any."""
    for i, arg in enumerate(args):
        if arg in ("-m", "--model") and i + 1 < len(args):
            return args[i + 1]
        if arg.startswith("--model="):
            return arg.split("=", 1)[1]
    return None
