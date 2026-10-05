"""The live dashboard: a local page that shows a Cliff or Swap run as it happens (epic Dashboard).

Everything comes from the run directory: the recipe, the journal, and the live output each
original run and tail writes. A finished run looks the same as a live one, so `tare watch`
can show any run directory.
"""
import json
import re
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib import resources
from pathlib import Path

from . import journal as journals
from .agents import AGENTS
from .cliff import wilson
from .swap import Cut


def _activity(agent_name: str | None, stdout: Path) -> str | None:
    """The latest thing the agent did, from the tail of its live output."""
    agent = AGENTS.get(agent_name or "")
    if not agent or not stdout.exists():
        return None
    with stdout.open("rb") as f:
        f.seek(max(0, stdout.stat().st_size - 64 * 1024))
        lines = f.read().decode(errors="replace").splitlines()
    for line in reversed(lines):
        try:
            described = agent.activity(json.loads(line))
        except ValueError:
            continue
        if described:
            return described
    return None


def _capsule_count(store: Path) -> int:
    return max(0, len(list((store / "capsules").glob("*.tar"))) - 1) if store.exists() else 0


def state(out: Path) -> dict:
    events = journals.read(out)
    recipe = out / "recipe.json"
    s = {"recipe": json.loads(recipe.read_text()) if recipe.exists() else None, "kind": None, "task": None,
         "check": None, "project": None, "sides": {}, "params": {}, "phase": "starting", "probes": [], "originals": {},
         "tails": [], "plan": [], "report": None, "started": events[0]["t"] if events else None,
         "updated": events[-1]["t"] if events else None, "now": time.time()}
    tails: dict[str, dict] = {}
    for e in events:
        kind = e["event"]
        if kind == "start":
            s.update({k: e.get(k) for k in ("kind", "task", "check", "project", "sides")})
            s["params"] = {k: e.get(k) for k in ("cuts", "tails", "budget")}
            if s["kind"] == "calibrate":
                s["originals"] = {k: {"passed": None, "detail": "", "steps": []} for k in s["sides"]}  # no original runs
        elif kind == "phase":
            s["phase"] = e["phase"]
        elif kind == "probe":
            s["probes"].append({k: e.get(k) for k in ("agent", "zero", "text")})
        elif kind == "original":
            s["originals"][e["side"]] = {"passed": e["passed"], "detail": e["detail"], "steps": e["steps"]}
        elif kind == "plan":
            s["plan"] = e["cuts"]
        elif kind == "tail":
            tail = tails.setdefault(e["id"], {"id": e["id"], "started": e["t"]})
            tail.update({k: v for k, v in e.items() if k not in ("t", "event")})
            if e["status"] != "running":
                tail["ended"] = e["t"]
        elif kind == "report":
            s["report"] = e["text"]

    # originals still running: their capsules so far and what the agent does right now
    for key, side in (s["sides"] or {}).items():
        if key not in s["originals"]:
            base = out / side.get("dir", ".")
            s["originals"][key] = {"running": True, "count": _capsule_count(base / "store"),
                                   "activity": _activity(side.get("agent"), base / "original" / "stdout.jsonl")}
    for tail in tails.values():
        if tail["status"] == "running":
            tail["activity"] = _activity(tail.get("agent_name"), out / tail["dir"] / "stdout.jsonl")
    s["tails"] = sorted(tails.values(), key=lambda t: (t["status"] != "running", -t["started"]))

    if s["kind"] == "cliff":
        s["steps"] = _cliff_steps(tails.values())
    elif s["kind"] == "swap":
        s["cells"] = _swap_cells(tails.values(), s["plan"])
    elif s["kind"] == "calibrate":
        s["rates"] = _rates(tails.values(), s["sides"])
    return s


def _cliff_steps(tails) -> list[dict]:
    steps: dict[int, list] = {}
    for t in tails:
        steps.setdefault(t["step"], []).append(t)
    rows = []
    for step, ts in sorted(steps.items()):
        done = [t["status"] == "passed" for t in ts if t["status"] != "running"]
        lo, hi = wilson(sum(done), len(done))
        rows.append({"step": step, "passes": sum(done), "n": len(done), "running": sum(t["status"] == "running" for t in ts),
                     "rate": sum(done) / len(done) if done else None, "lo": lo, "hi": hi})
    return rows


def _rates(tails, sides) -> dict:
    rates = {}
    for key in sides:
        ts = [t for t in tails if t.get("side") == key]
        done = [t["status"] == "passed" for t in ts if t["status"] != "running"]
        lo, hi = wilson(sum(done), len(done))
        # a judge check reports "score N" in its detail line
        scores = [int(m.group(1)) for t in ts if t["status"] != "running"
                  and (m := re.search(r"score (\d+)", t.get("detail", "")))]
        rates[key] = {"passes": sum(done), "n": len(done), "running": sum(t["status"] == "running" for t in ts),
                      "rate": sum(done) / len(done) if done else None, "lo": lo, "hi": hi, "scores": scores,
                      "mean": sum(scores) / len(scores) if scores else None,
                      "times": [t["ended"] - t["started"] for t in ts if "ended" in t]}
    return rates


def _swap_cells(tails, plan) -> list[dict]:
    cuts = []
    for i, p in enumerate(plan):
        cut = Cut(p["fraction"], p["steps"])
        running: dict[tuple[str, str], int] = {}
        for t in tails:
            if t.get("cut") != i:
                continue
            native = t["kind"] == "native"
            key = ("native" if native else t["room"], t["room"] if native else t["agent"])
            target = cut.native.setdefault(t["room"], []) if native else cut.cells.setdefault(key, [])
            if t["status"] == "running":
                running[key] = running.get(key, 0) + 1
            else:
                target.append(t["status"] == "passed")
        complete = all(cut.cells.get((r, m)) for r in "ab" for m in "ab")
        cuts.append({
            "fraction": p["fraction"], "steps": p["steps"],
            "cells": {f"{r}{m}": {"passes": sum(cut.cells.get((r, m), [])), "n": len(cut.cells.get((r, m), [])),
                                  "running": running.get((r, m), 0)} for r in "ab" for m in "ab"},
            "native": {r: {"passes": sum(v), "n": len(v), "running": running.get(("native", r), 0)}
                       for r, v in cut.native.items()},
            "state": cut.state() if complete else None, "model": cut.model() if complete else None,
        })
    return cuts


def serve(out: Path, port: int = 0) -> tuple[ThreadingHTTPServer, str]:
    """Serve the dashboard for a run directory on 127.0.0.1; returns the server and its URL."""
    page = resources.files("tare").joinpath("dashboard.html").read_bytes()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            if self.path.startswith("/state"):
                body, kind = json.dumps(state(out)).encode(), "application/json"
            elif self.path in ("/", "/index.html"):
                body, kind = page, "text/html; charset=utf-8"
            else:
                self.send_response(404)
                self.send_header("content-length", "0")
                self.end_headers()
                return
            self.send_response(200)
            self.send_header("content-type", kind)
            self.send_header("cache-control", "no-store")
            self.send_header("content-length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f"http://localhost:{server.server_address[1]}/"
