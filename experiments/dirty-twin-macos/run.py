"""Dirty-twin test on macOS: Claude Code, Codex and Pi in a Seatbelt room (see PLAN.md).

usage:
  uv run experiments/dirty-twin-macos/run.py markers                     # write markers.local.json, print hashes
  uv run experiments/dirty-twin-macos/run.py run claude|codex|pi t0|t1|t2
  uv run experiments/dirty-twin-macos/run.py keychain                    # digest and count of Claude's item
  uv run experiments/dirty-twin-macos/run.py check                       # score every run

T0 is the dirty twin as `tare probe` starts it. T1 is the Seatbelt room as `tare probe`
builds it. T2 is that room with parts of the real setup copied into the room's own copy
(PLANTED). Runs land in runs/<agent>/<condition>/ (not committed): request bodies, stdout,
stderr, exit code, reach. The work directory is this repository, as `tare probe` uses it.
"""
import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from tare.agents import AGENTS, Capture, Real
from tare.fake import Fake
from tare.probe import REACH_SCRIPT, SECRET_PATHS, render, score
from tare.room import Room, _clone, _user_dir, backend

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
HOME = Path.home()
PLANTED_ENV = {"TARE_PLANTED_VARIABLE": "planted"}
# where macOS keeps what a room must not reach (#86), beside tare's SECRET_PATHS
MAC_TARGETS = [str(HOME / "Library" / p) for p in ("Keychains", "Preferences", "Application Support")] + [
    str(_user_dir()), f"/private/tmp/claude-{os.getuid()}", "/private/var/tmp", "/Users/Shared"]
# the reach script, plus the pasteboard (not a path)
REACH = REACH_SCRIPT + '; if pbpaste >/dev/null 2>&1; then echo "pasteboard readable"; fi'


def sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:16]


def markers():
    """The marker strings, read from the real setup and kept local; only their hashes are printed."""
    memory = next(line.strip()[:80] for line in (HOME / ".codex/memories/memory_summary.md").read_text().splitlines()
                  if len(line.strip()) >= 30)
    email = json.loads((HOME / ".claude.json").read_text())["oauthAccount"]["emailAddress"]
    project = "**Epic → features → one branch and one PR → epic closed.**"
    found = {
        "claude": {"C1": "codies-memory:memory-boot", "C2": "mcp__claude_ai_", "C3": "anthropic-skills:",
                   "C4": email, "C5": f"{HOME}/", "C6": project},
        "codex": {"X1": memory, "X2": "agent-browser", "X3": f"{HOME}/", "X4": project, "X5": "mcp__qmd__"},
        "pi": {"I1": "<name>apple-design</name>", "I2": "web_search", "I3": f"{HOME}/", "I4": project},
    }
    (HERE / "markers.local.json").write_text(json.dumps(found, ensure_ascii=False, indent=1))
    for agent, ms in found.items():
        print(agent, "  ".join(f"{k}={sha(v)}" for k, v in ms.items()))


def keychain():
    account, service = AGENTS["claude"].keychain_item()
    digest = subprocess.run(f'security find-generic-password -a "{account}" -s "{service}" -w | shasum -a 256',
                            shell=True, capture_output=True, text=True).stdout[:16]
    dump = subprocess.run(["security", "dump-keychain"], capture_output=True, text=True).stdout
    print(f"Claude Keychain item: digest {digest}, items {dump.count('\"svce\"<blob>=\"Claude Code-credentials')}")


def plant(name: str, agent, room: Room) -> list[str]:
    """Copy parts of the real setup into the room's own copy. Returns extra CLI flags."""
    config = room.config(agent)
    if name == "claude":
        plugin = HOME / ".claude/plugins/cache/limitless/codies-memory/1.2.3"
        _clone(plugin, room.home / "planted-plugin")
        return ["--plugin-dir", str(room.home / "planted-plugin")]  # and no room flags: connectors, account skills
    if name == "codex":
        (config / "memories").mkdir()
        shutil.copyfile(HOME / ".codex/memories/memory_summary.md", config / "memories/memory_summary.md")
        _clone((HOME / ".agents/skills/agent-browser").resolve(), room.home / ".agents/skills/agent-browser")
        return []
    _clone((HOME / ".pi/agent/skills/apple-design").resolve(), config / "skills/apple-design")
    _clone(HOME / ".pi/agent/npm", config / "npm")
    settings = json.loads((config / "settings.json").read_text())
    (config / "settings.json").write_text(json.dumps(settings | {"packages": ["npm:pi-web-access"]}))
    return []


def run(name: str, condition: str):
    out = HERE / "runs" / name / condition
    out.mkdir(parents=True, exist_ok=True)
    agent = AGENTS[name]
    real = agent.discover()
    targets = [str(real.home), str(real.config), *(str(real.home / p) for p in SECRET_PATHS), *MAC_TARGETS]
    reach = ["/bin/sh", "-c", REACH, "reach", *targets]

    def save(prefix: str, proc, fake):
        (out / f"{prefix}stdout.jsonl").write_text(proc.stdout)
        (out / f"{prefix}stderr.log").write_text(proc.stderr)
        (out / f"{prefix}exit").write_text(str(proc.returncode))
        (out / f"{prefix}bodies.json").write_text(json.dumps(fake.requests, ensure_ascii=False))
        print(f"{name} {condition} {prefix or 'main'}: exit {proc.returncode}, {len(fake.requests)} bodies")

    if condition == "t0":
        # as tare probe starts the dirty twin: the real setup, minus what a parent Claude Code session exports
        env = {k: v for k, v in os.environ.items() if not k.startswith("CLAUDE") or k == "CLAUDE_CONFIG_DIR"}
        with Fake() as fake:
            args, extra = agent.probe(fake.url)
            with agent.twin(real, fake.url) as twin:
                proc = subprocess.run([str(real.binary), *args], env=env | extra | twin, cwd=REPO, capture_output=True,
                                      text=True, timeout=300, stdin=subprocess.DEVNULL)
            save("", proc, fake)
        outside = subprocess.run(reach, capture_output=True, text=True, timeout=60)
        (out / "reach_out.txt").write_text(outside.stdout)
        return
    rooms = backend()
    with rooms.open(agent, real, REPO) as room:
        flags = agent.room_flags
        env = {}
        if condition == "t2":
            extra_flags = plant(name, agent, room)
            flags = [] if name == "claude" else flags
            flags, env = [*flags, *extra_flags], PLANTED_ENV
        runs = [("", flags)] + ([("bare-", [*flags, *agent.bare_flags])] if getattr(agent, "bare_flags", None) else [])
        for prefix, run_flags in runs:
            with Fake() as fake:
                agent.prepare_probe(room.config(agent), fake.url)
                args, extra = agent.probe(fake.url)
                proc = subprocess.run(rooms.argv(room, agent, real, [agent.name, *run_flags, *args], extra | env),
                                      capture_output=True, text=True, timeout=300, stdin=subprocess.DEVNULL)
                save(prefix, proc, fake)
        inside = subprocess.run(rooms.argv(room, agent, real, reach, env), capture_output=True, text=True, timeout=60)
        (out / "reach_in.txt").write_text(inside.stdout)
        (out / "room.json").write_text(json.dumps({"inside_home": room.inside_home, "inside_work": room.inside_work,
                                                   "env": room.env}))


def capture(name: str, condition: str, prefix: str = "") -> Capture | None:
    out = HERE / "runs" / name / condition
    if not (out / f"{prefix}exit").exists():
        return None
    return AGENTS[name].capture((out / f"{prefix}stdout.jsonl").read_text(),
                                json.loads((out / f"{prefix}bodies.json").read_text()))


def check():
    found = json.loads((HERE / "markers.local.json").read_text())
    for name, ms in found.items():
        agent = AGENTS[name]
        real: Real = agent.discover()
        print(f"\n===== {name}")
        caps = {c: capture(name, c) for c in ("t0", "t1", "t2")}
        for c, cap in caps.items():
            if cap is None:
                print(f"{c}: no capture")
                continue
            text = cap.text + "\n" + "\n".join(cap.tools)
            print(f"{c}: {len(cap.text)} chars, {len(cap.tools)} tools; markers: "
                  + "  ".join(f"{k}={'YES' if v in text else 'no'}" for k, v in ms.items()))
        twin = caps["t0"]
        reach_out = (HERE / "runs" / name / "t0" / "reach_out.txt").read_text() if twin else ""
        print("reach outside:", " ".join(line.split(" ", 1)[1].replace(str(HOME), "~")
                                         for line in reach_out.splitlines() if line.startswith("path ")))
        for c in ("t1", "t2"):
            out = HERE / "runs" / name / c
            if twin is None or caps[c] is None:
                continue
            meta = json.loads((out / "room.json").read_text())
            built = Room(Path(meta["inside_home"]), REPO, None, meta["inside_home"], meta["inside_work"], env=meta["env"])
            reach_in = (out / "reach_in.txt").read_text()
            print(f"--- {c} reach inside: {' '.join(reach_in.split()) or 'nothing'}")
            reading = score(agent, real, twin, caps[c], reach_in, reach_out, bare=capture(name, c, "bare-"),
                            project=REPO, built=built)
            print(render(reading, REPO).replace(str(HOME), "~"))


if __name__ == "__main__":
    {"markers": markers, "keychain": keychain, "check": check}.get(sys.argv[1], lambda: run(sys.argv[2], sys.argv[3]))()
