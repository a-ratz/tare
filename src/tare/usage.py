"""Usage: the tokens and the cost of agent runs (epic Token and cost tracking).

Each adapter reads its agent's own stream after a run into one shape. `input` counts every
input token, cached ones included, and `cached` is the part read from a prompt cache. `cost_usd`
is what the agent itself reports, or None when it reports none. Sums keep count of the runs
whose cost is unknown, so a total never looks complete when it is not.
"""
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
