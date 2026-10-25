"""The answer at the top of a run page: one sentence in plain words, the figures behind it, and how
far to trust them (epic #138).

Everything comes from the dashboard's state, never from the report's wording, so a live run, a
finished one and one recorded by an older tare read alike. The sentences follow fixed templates
per verdict; the verdicts are worked out the way Calibrate, Swap and Cliff work them out.
"""
import re

from .cliff import wilson
from .swap import leader, newcombe

PRODUCTS = {"claude": "Claude Code", "codex": "Codex", "pi": "Pi", "agy": "Antigravity CLI"}
JUDGE = re.compile(r"score (\d+) \(threshold (\d+)\)(?:: (.*))?", re.S)
# a step's tool and its argument, as the trail describes it: "Bash echo hi > a.txt", "Write /work/x"
ACTS = {"Bash": "ran", "Write": "wrote", "Edit": "edited", "MultiEdit": "edited", "Read": "read",
        "exec_command": "ran", "shell": "ran", "apply_patch": "patched", "write": "wrote", "edit": "edited",
        "bash": "ran", "read": "read"}


def judged(detail: str) -> dict | None:
    """The judge's score, threshold and one-sentence reason from a run's detail line."""
    m = JUDGE.search(detail or "")
    return {"score": int(m.group(1)), "threshold": int(m.group(2)), "reason": (m.group(3) or "").strip()} if m else None


def _model(args: list[str]) -> str | None:
    for i, arg in enumerate(args):
        if arg in ("--model", "-m") and i + 1 < len(args):
            return args[i + 1]
        if arg.startswith("--model="):
            return arg.split("=", 1)[1]
    return None


def names(sides: dict) -> dict[str, dict[str, str]]:
    """Each side by product name; the model joins in when two sides share an agent."""
    products = [PRODUCTS.get(v.get("agent"), v.get("agent") or k) for k, v in sides.items()]
    out = {}
    for (key, side), product in zip(sides.items(), products):
        model = _model(side.get("args") or [])
        shared = products.count(product) > 1
        full = f"{product} with {model}" if shared and model else f"{product} ({key})" if shared else product
        out[key] = {"name": product, "full": full, "label": f"{product} · {model}" if model else product}
    return out


def pct(x: float) -> str:
    return f"{round(x * 100)}%"


def duration(seconds: float) -> str:
    s = max(0, round(seconds))
    if s >= 3600:
        return f"{s // 3600}h {s % 3600 // 60:02d}m"
    return f"{s // 60}m {s % 60:02d}s" if s >= 60 else f"{s}s"


def _count(n: int, word: str) -> str:
    n = max(0, n)
    return f"{n} {word}{'' if n == 1 else 's'}"


def _join(items: list[str]) -> str:
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " and " + items[-1]


def _rooms(probes: list[dict]) -> dict | None:
    """The trust line's first fact: whether every room was proven clean."""
    if not probes:
        return None
    bad = [p for p in probes if not p.get("zero")]
    if not bad:
        return {"cell": "ok", "text": "Room proven clean" if len(probes) == 1 else
                ("Both rooms proven clean" if len(probes) == 2 else "Every room proven clean")}
    agents = _join([PRODUCTS.get(p["agent"], p["agent"]) for p in bad])
    blind = all("not proven" in (p.get("text") or "") for p in bad)
    return {"cell": "failed", "text": f"{agents}: room {'not proven clean' if blind else 'not clean'}, run with --allow-dirty"}


def answer(s: dict) -> dict:
    """The kicker, the sentence, a paragraph, the figures and the trust line for a run's state."""
    if not s.get("kind") or not s.get("sides"):
        return {"kicker": "tare", "sentence": "Waiting for the run to start.", "detail": "", "figures": [], "trust": []}
    nm = names(s["sides"])
    result = {"calibrate": _calibrate, "swap": _swap, "cliff": _cliff}[s["kind"]](s, nm)
    rooms = _rooms(s.get("probes") or [])
    if rooms:
        result["trust"].insert(0, rooms)
    return result


# --- Calibrate -----------------------------------------------------------------------------------

def _calibrate(s: dict, nm: dict) -> dict:
    rates, keys = s.get("rates") or {}, list(s["sides"])
    per = (s.get("params") or {}).get("tails") or 0
    done = sum(r["n"] for r in rates.values())
    total = per * len(keys)
    live = s.get("phase") != "done"
    scores = {k: rates[k]["scores"] for k in keys if k in rates and rates[k].get("scores")}
    out = {"figures": [], "trust": [], "detail": ""}
    if not done:
        out.update(kicker="tare calibrate · How often does each agent pass?",
                   sentence=f"Still running: no run has finished yet. Each agent runs {per} times from scratch.")
        out["trust"].append({"cell": "running", "text": f"0 of {total} runs done"})
        return out

    if scores:
        out["kicker"] = "tare calibrate · How did each agent score?"
        means = {k: round(sum(v) / len(v)) for k, v in scores.items()}
        order = sorted(means, key=lambda k: -means[k])
        verb = "scores" if live else "scored"
        if len(order) == 1:
            sentence = f"{nm[order[0]]['full']} {verb} {means[order[0]]} out of 100, on average."
        elif len(set(means.values())) == 1:
            sentence = f"Both {verb} {means[order[0]]} out of 100, on average." if len(order) == 2 else \
                f"Every agent {verb} {means[order[0]]} out of 100, on average."
        elif len(order) == 2:
            a, b = order
            sentence = f"{nm[a]['full']} {verb} higher: {means[a]} against {means[b]} out of 100, on average."
        else:
            sentence = (f"{nm[order[0]]['full']} {verb} highest: {means[order[0]]} out of 100, on average, against "
                        + _join([f"{nm[k]['full']} with {means[k]}" for k in order[1:]]) + ".")
        for k in order:
            out["figures"].append({"value": str(means[k]), "unit": "/ 100", "label": [nm[k]["label"], "average score"]})
        passed = sum(rates[k]["passes"] for k in keys)
        out["figures"].append({"value": str(passed), "unit": f"of {done}", "label": ["runs passed", "the check"]})
        paragraph = [f"Each agent ran the task {per} times, each time from scratch in a clean room."]
        if passed == done and len(order) == 2:
            a, b = order
            paragraph.append("Every run passed the check, so the judge's scores tell them apart"
                             + (f": every {nm[a]['full']} run scored above every {nm[b]['full']} run."
                                if min(scores[a]) > max(scores[b]) else "."))
        out["detail"] = " ".join(paragraph)
        out["trust"].append({"cell": "ok", "text": "The judge saw no agent or model names"})
    elif s.get("check"):
        out["kicker"] = "tare calibrate · How often does each agent pass?"
        order = sorted(keys, key=lambda k: -(rates[k]["rate"] or 0))
        verb = "passes" if live else "passed"
        if len({(rates[k]["passes"], rates[k]["n"]) for k in keys}) == 1 and len(keys) > 1:
            r = rates[keys[0]]
            sentence = f"{'Both' if len(keys) == 2 else 'Every agent'} {verb} {r['passes']} of {r['n']} runs."
        else:
            first, *rest = order
            sentence = (f"{nm[first]['full']} {verb} {rates[first]['passes']} of {rates[first]['n']} runs"
                        + ("" if not rest else ", " + ", ".join(
                            f"{nm[k]['full']} {rates[k]['passes']} of {rates[k]['n']}" for k in rest)) + ".")
        for k in order:
            out["figures"].append({"value": str(rates[k]["passes"]), "unit": f"of {rates[k]['n']}",
                                   "label": [nm[k]["label"], "passed"]})
        out["detail"] = f"Each agent ran the task {per} times, each time from scratch in a clean room."
    else:
        out["kicker"] = "tare calibrate · How long does each agent take?"
        times = {k: rates[k]["times"] for k in keys if rates.get(k, {}).get("times")}
        finished = all(rates[k]["passes"] == rates[k]["n"] for k in keys)
        lead = ("Both agents finished every run." if len(keys) == 2 else "Every agent finished every run.") \
            if finished else _join([f"{nm[k]['full']} finished {rates[k]['passes']} of {rates[k]['n']} runs"
                                    for k in keys]) + "."
        took = [f"{nm[k]['full']} took {duration(sum(v) / len(v))}" for k, v in times.items()]
        sentence = lead + (" " + _join(took) + " on average." if took else "")
        for k, v in times.items():
            out["figures"].append({"value": duration(sum(v) / len(v)), "unit": "",
                                   "label": [nm[k]["label"], "average time"]})
        out["detail"] = (f"Each agent ran the task {per} times, each time from scratch in a clean room. "
                         "There was no check, so tare kept every finished workspace for you to score.")
    out["sentence"] = ("So far, " + sentence[0].lower() + sentence[1:]) if live and sentence.startswith(("Both", "Every")) \
        else (f"So far: {sentence}" if live else sentence)

    if s.get("check"):
        spans = {(round(rates[k]["lo"], 2), round(rates[k]["hi"], 2)) for k in keys if rates[k]["n"]}
        if len(spans) == 1:
            lo, hi = next(iter(spans))
            ranges = f"each pass rate is likely between {pct(lo)} and {pct(hi)}"
        else:
            ivs = sorted((rates[k]["lo"], rates[k]["hi"]) for k in keys if rates[k]["n"])
            apart = all(ivs[i][1] < ivs[i + 1][0] for i in range(len(ivs) - 1))
            ranges = "the likely ranges of the pass rates do not overlap" if apart else \
                "the likely ranges of the pass rates overlap"
        out["trust"].append({"cell": "limit", "text": f"{per} runs per agent: {ranges}"})
    if live:
        out["trust"].append({"cell": "running", "text": f"{done} of {total} runs done"})
    return out


# --- Swap ----------------------------------------------------------------------------------------

def _point(fraction: float) -> str:
    return {0.0: "the start", 0.5: "halfway", 1.0: "the end"}.get(round(fraction, 2), f"{round(fraction * 100)}% of the way")


def _at(fraction: float) -> str:
    """The handover point as a time adverbial: "at the start", "halfway", "at the end"."""
    point = _point(fraction)
    return point if point == "halfway" else f"at {point}"


def _from(fraction: float) -> str:
    """Where a pattern begins and holds to the end: "From halfway on,", or "At the end," for the last point."""
    return "At the end," if round(fraction, 2) == 1.0 else f"From {_point(fraction)} on,"


def _swap(s: dict, nm: dict) -> dict:
    cuts = s.get("cells") or []
    a, b = nm["a"]["full"], nm["b"]["full"]
    tails = (s.get("params") or {}).get("tails") or 0
    out = {"kicker": "tare swap · Workspace or agent: which decided?", "figures": [], "trust": [], "detail": ""}
    live = s.get("phase") != "done"
    complete = [c for c in cuts if c.get("state") and c.get("model")]
    restarts = sum(v["n"] for c in cuts for v in list(c["cells"].values()) + list(c["native"].values()))
    running = sum(v["running"] for c in cuts for v in list(c["cells"].values()) + list(c["native"].values()))
    originals = s.get("originals") or {}
    if not complete:
        if any(o.get("running") for o in originals.values()) or not cuts:
            out["sentence"] = "Each agent is trying the task once first."
        else:
            out["sentence"] = f"Still running: {restarts} restarts done so far."
        if live:
            out["trust"].append({"cell": "running", "text": f"{restarts} restarts done, {running} running"})
        return out

    dominant = [leader(c["state"], c["model"]) for c in complete]
    wins = {agent: sum(c["cells"][r + agent]["passes"] for c in complete for r in "ab") for agent in "ab"}
    rooms = {room: sum(c["cells"][room + agent]["passes"] for c in complete for agent in "ab") for room in "ab"}
    winner, loser = (a, b) if wins["a"] >= wins["b"] else (b, a)
    better = f"{a}'s" if rooms["a"] >= rooms["b"] else f"{b}'s"
    shown = [d for d in dominant if d != "neither"]
    late = next((i for i, d in enumerate(dominant) if d in ("room", "tie") and "model" in dominant[:i]), None)
    if late is not None and dominant[late] == "tie" and "room" not in dominant:
        until = _point(complete[late - 1]["fraction"])
        sentence = (f"The agent decided {'at the start' if until == 'the start' else 'until ' + until}. "
                    f"{_from(complete[late]['fraction'])} workspace and agent weighed about the same.")
    elif "room" in dominant and "model" in dominant[:dominant.index("room")]:
        at = dominant.index("room")
        until = _point(complete[max(i for i in range(at) if dominant[i] == "model")]["fraction"])
        sentence = (f"The agent decided {'at the start' if until == 'the start' else 'until ' + until}. "
                    f"{_from(complete[at]['fraction'])} the workspace decided.")
    elif not shown:
        sentence = "Neither the workspace nor the agent made a clear difference."
    elif set(shown) == {"model"}:
        sentence = f"The agent decided, not the workspace: {winner} passed more often in either workspace."
    elif set(shown) == {"room"}:
        sentence = f"The workspace decided, not the agent: both did better in {better} workspace."
    else:
        words = {"room": "the workspace", "model": "the agent", "tie": "both alike", "neither": "neither"}
        sentence = "No single pattern: " + "; ".join(
            f"{_at(c['fraction'])} {words[d]}" for c, d in zip(complete, dominant)) + "."
    out["sentence"] = f"So far: {sentence}" if live else sentence

    deciding = [c["state"] if d in ("room", "tie") else c["model"] for c, d in zip(complete, dominant) if d != "neither"]
    told = []
    for key, name in (("a", a), ("b", b)):
        o = originals.get(key) or {}
        if "passed" in o and o["passed"] is not None:
            told.append(f"{name}'s run {'passed' if o['passed'] else 'failed'}")
    points = _join([_at(c["fraction"]) for c in cuts])
    out["detail"] = " ".join(filter(None, [
        f"Each agent tried the task once: {_join(told)}." if told else "",
        f"tare then swapped their unfinished work {points} and let each agent continue each workspace "
        f"{tails} times.",
        "The likely ranges behind this include zero, so more restarts would settle it."
        if any(lo <= 0 <= hi for _, lo, hi in deciding) else ""]))

    first, last = complete[0], complete[-1]
    e = first["model"][0]
    out["figures"].append({"value": str(round(abs(e) * 100)), "unit": "points",
                           "label": [f"{a if e >= 0 else b} ahead in the same", f"workspaces {_at(first['fraction'])}"]})
    w = last["state"][0]
    out["figures"].append({"value": str(round(abs(w) * 100)), "unit": "points",
                           "label": [f"{a if w >= 0 else b}'s workspace ahead", _at(last["fraction"])]})
    took = duration(s["updated"] - s["started"]) if s.get("started") and s.get("updated") else None
    out["figures"].append({"value": str(restarts), "unit": "", "label": ["restarts", f"in {took}" if took else "in all"]})

    if first["fraction"] == 0:
        _, lo, hi = first["state"]
        out["trust"].append({"cell": "ok", "text": "At the start both workspaces were the same project and made no clear difference"}
                            if lo <= 0 <= hi else
                            {"cell": "failed", "text": "At the start the identical workspaces differed: do not trust the effects"})
    costs = []
    for c in complete:
        for side, v in c["native"].items():
            own = c["cells"][side + side]
            if v["n"] and own["n"]:
                costs.append(newcombe(v["passes"], v["n"], own["passes"], own["n"]))
    if costs:
        out["trust"].append({"cell": "ok", "text": "The handover note cost nothing clear"}
                            if all(lo <= 0 <= hi for _, lo, hi in costs) else
                            {"cell": "limit", "text": "The handover note cost some passes against the agent's own session"})
    if tails and tails <= 5:
        out["trust"].append({"cell": "limit", "text": f"{tails} restarts per box: the likely ranges are wide"})
    if live:
        out["trust"].append({"cell": "running", "text": f"{restarts} restarts done, {running} running"})
    return out


# --- Cliff ---------------------------------------------------------------------------------------

def act(description: str) -> str:
    """What the agent did in a step, as a verb phrase: "ran `echo hi`", "wrote index.html"."""
    last = (description or "").split(" + ")[-1]
    tool, _, arg = last.partition(" ")
    arg = arg.removeprefix("/work/")
    verb = ACTS.get(tool)
    if verb == "ran":
        return f"ran `{arg}`"
    if verb:
        return f"{verb} {arg}"
    return f"made a {tool} call" if tool else "took that step"


def _cliff(s: dict, nm: dict) -> dict:
    rows = {r["step"]: r for r in s.get("steps") or []}
    o = (s.get("originals") or {}).get("a") or {}
    steps = o.get("steps") or []
    agent = nm["a"]["full"]
    params = s.get("params") or {}
    live = s.get("phase") != "done"
    out = {"kicker": "tare cliff · Where did the run go wrong?", "figures": [], "trust": [], "detail": ""}
    spent = sum(r["n"] for r in rows.values())
    running = sum(r["running"] for r in rows.values())

    def rate(step):
        r = rows.get(step)
        return r["passes"] / r["n"] if r and r["n"] else None

    if o.get("running"):
        out["sentence"] = f"The original run is still going: {o.get('count', 0)} steps so far."
        return out
    if o.get("passed"):
        out["sentence"] = "The run passed, so no step lost it."
        out["detail"] = "Cliff looks for the step where a failed run was lost. This run passed its check."
        return out
    base = rate(0)
    if base is None:
        out["sentence"] = f"The run failed after {_count(len(steps) - 1, 'step')}. Restarts begin shortly."
        if live:
            out["trust"].append({"cell": "running", "text": f"{spent} restarts done, {running} running"})
        return out

    fresh = rows[0]
    if base == 0:
        hi = wilson(fresh["passes"], fresh["n"])[1]
        if hi < 0.2:
            out["sentence"] = f"The task is too hard for {agent}: even a fresh start passes 0 of {fresh['n']} times."
        elif live:
            out["sentence"] = f"Still searching. So far, no fresh start has passed: 0 of {fresh['n']}."
        else:
            out["sentence"] = f"The task looks too hard for {agent}: no fresh start passed, 0 of {fresh['n']}."
            out["trust"].append({"cell": "limit", "text": f"Only {fresh['n']} fresh starts: even a pass rate of "
                                 f"{pct(hi)} would fit them"})
        out["detail"] = (f"The original run failed after {_count(len(steps) - 1, 'step')}. When even a fresh start never "
                         "passes, no single step lost the run: the task is beyond the model.")
        out["figures"].append({"value": "0", "unit": f"of {fresh['n']}", "label": ["fresh starts", "passed"]})
    else:
        tau = base / 2
        probed = sorted(k for k in rows if rows[k]["n"])
        lows = [k for k in probed if k > 0 and rate(k) < tau]
        last = probed[-1]
        if not lows:
            out["sentence"] = (f"The run was unlucky, not lost: restarted at its last step, it still passes "
                               f"{rows[last]['passes']} of {rows[last]['n']} times.") if last > 0 else \
                f"Still searching. So far, a fresh start passes {fresh['passes']} of {fresh['n']} times."
            if last > 0:
                out["detail"] = (f"The original run failed after {_count(len(steps) - 1, 'step')}. Restarted from its last "
                                 f"step, it passed {rows[last]['passes']} of {rows[last]['n']} times, at least half as "
                                 f"often as a fresh start ({fresh['passes']} of {fresh['n']}), so no single step lost it.")
            out["figures"] += [{"value": pct(base), "unit": "", "label": ["pass rate of", "a fresh start"]}]
            if last > 0:
                out["figures"].append({"value": pct(rate(last)), "unit": "", "label": ["pass rate when", f"restarted at step {last}"]})
        else:
            low = min(lows)
            high = max(k for k in probed if k < low and rate(k) >= tau)
            lo_h, hi_h = wilson(rows[high]["passes"], rows[high]["n"])
            lo_l, hi_l = wilson(rows[low]["passes"], rows[low]["n"])
            what = act(steps[low]) if low < len(steps) else "took that step"
            if low - high > 1:
                sentence = f"The run went wrong somewhere between step {high} and step {low}."
            elif lo_h > hi_l:
                sentence = f"The run went wrong at step {low}, when the agent {what}."
            else:
                sentence = f"The run most likely went wrong at step {low}, when the agent {what}."
            out["sentence"] = f"So far: {sentence}" if live else sentence
            start = "a fresh start" if high == 0 else f"step {high}"
            after = [k for k in probed if k > low]
            rebounds = [k for k in after if rate(k) >= tau]
            out["detail"] = (f"The original run failed after {_count(len(steps) - 1, 'step')}. tare restarted the agent from "
                             f"saved steps of it. From {start} it still passed {rows[high]['passes']} of "
                             f"{rows[high]['n']} times; from step {low} "
                             + ("on, it never passed again." if not rebounds and rows[low]["passes"] == 0 else
                                f"only {rows[low]['passes']} of {rows[low]['n']}."))
            out["figures"] += [
                {"value": f"Step {low}", "unit": "", "label": ["where the run", "was lost"] if low - high == 1
                 else ["the latest step", "it could be lost at"]},
                {"value": pct(rate(high)), "unit": "", "label": ["pass rate when", f"restarted at {start}" if high else "starting fresh"]},
                {"value": pct(rate(low)), "unit": "", "label": ["pass rate when", f"restarted at step {low}"]},
            ]
            if after:
                out["trust"].append({"cell": "ok", "text": f"No step after {low} passes again"} if not rebounds else
                                    {"cell": "limit", "text": f"Step{'s' if len(rebounds) > 1 else ''} "
                                     f"{_join([str(k) for k in rebounds])} pass{'es' if len(rebounds) == 1 else ''} again after {low}"})
            if low - high == 1:
                apart = lo_h > hi_l
                out["trust"].append({"cell": "ok" if apart else "limit",
                                     "text": (f"Likely ranges {'do not overlap' if apart else 'still overlap'}: "
                                              f"{round(lo_h * 100)}–{round(hi_h * 100)}% before, "
                                              f"{round(lo_l * 100)}–{round(hi_l * 100)}% after")})
    budget = params.get("budget")
    if budget and spent >= budget:
        out["trust"].append({"cell": "limit", "text": f"All {budget} restarts of the budget used"})
    if live:
        out["trust"].append({"cell": "running", "text": f"{spent} restarts done, {running} running"})
    return out
