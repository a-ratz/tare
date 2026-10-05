#!/usr/bin/env python3
"""Score dirty-twin runs against the markers (see PLAN.md).

usage: uv run check.py MARKERS_JSON --ref runs/r0 runs/t0 runs/t1

Prints marker ids, never marker strings, so the output can be quoted in RESULTS.md.
"""
import argparse
import json
from pathlib import Path


def load(run: Path):
    reqs = [json.loads(p.read_text()) for p in sorted((run / "captures").glob("*.json"))]
    init = None
    stream = run / "stream.jsonl"
    if stream.exists():
        for line in stream.read_text().splitlines():
            try:
                event = json.loads(line)
            except ValueError:
                continue
            if event.get("type") == "system" and event.get("subtype") == "init":
                init = event
                break
    rc = (run / "exit").read_text().strip() if (run / "exit").exists() else "?"
    return reqs, init, rc


def tool_result_lines(reqs):
    lines = []
    for r in reqs:
        for msg in (r["body"] or {}).get("messages", []):
            content = msg.get("content")
            if not isinstance(content, list):
                continue
            for block in content:
                if block.get("type") != "tool_result":
                    continue
                inner = block.get("content")
                text = inner if isinstance(inner, str) else "\n".join(
                    b.get("text", "") for b in inner or [] if isinstance(b, dict))
                lines += [l for l in text.splitlines() if l.startswith(("REACH ", "absent ", "ENV "))]
    return sorted(set(lines))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("markers", type=Path)
    ap.add_argument("--ref", type=Path, required=True)
    ap.add_argument("runs", type=Path, nargs="+")
    args = ap.parse_args()
    markers = json.loads(args.markers.read_text())

    _, ref_init, ref_rc = load(args.ref)
    ref_tools = set(ref_init["tools"]) if ref_init else set()
    print(f"== {args.ref.name} (reference, exit {ref_rc}): init tools {len(ref_tools)}")
    if ref_init:
        print("   init keys:", ", ".join(sorted(ref_init)))
        print("   mcp servers:", ", ".join(f"{s.get('name')}={s.get('status')}" for s in ref_init.get("mcp_servers", [])))

    for run in args.runs:
        reqs, init, rc = load(run)
        msgs = [r for r in reqs if r["method"] == "POST" and r["path"].split("?")[0].endswith("/v1/messages")]
        main_loop = [r for r in msgs if r["body"].get("tools")]
        other = sorted({f"{r['method']} {r['path'].split('?')[0]}" for r in reqs if r not in msgs})
        blob = "\n".join(json.dumps(r["body"], ensure_ascii=False) for r in reqs)
        offered = {t["name"] for r in main_loop for t in r["body"]["tools"]}
        print(f"\n== {run.name} (exit {rc}): {len(reqs)} requests, {len(msgs)} to /v1/messages, "
              f"{len(main_loop)} main-loop")
        if other:
            print("   other paths:", ", ".join(other))
        print("   markers:", "  ".join(f"{k}={'YES' if v in blob else 'no'}" for k, v in markers.items()))
        print(f"   tools offered: {len(offered)}; init tools: {len(init['tools']) if init else '-'}")
        if init:
            print("   mcp servers:", ", ".join(f"{s.get('name')}={s.get('status')}" for s in init.get("mcp_servers", [])) or "-")
        missing = sorted(ref_tools - offered)
        extra = sorted(offered - ref_tools)
        print(f"   vs {args.ref.name} init: {len(missing)} missing, {len(extra)} extra")
        for name in missing:
            print(f"     - {name}")
        for name in extra:
            print(f"     + {name}")
        for line in tool_result_lines(reqs):
            print("   " + line)


if __name__ == "__main__":
    main()
