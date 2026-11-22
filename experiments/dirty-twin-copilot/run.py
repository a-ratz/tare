"""Dirty-twin test for the GitHub Copilot CLI (see PLAN.md).

usage:
  uv run experiments/dirty-twin-copilot/run.py markers              # write markers.local.json, print hashes
  uv run experiments/dirty-twin-copilot/run.py run t0|t0off|t1|t1f|t2|r1
  uv run experiments/dirty-twin-copilot/run.py check                # score every run against the markers

The fake is reached through Copilot's "bring your own key" variables (COPILOT_PROVIDER_BASE_URL,
COPILOT_PROVIDER_TYPE=anthropic, COPILOT_MODEL): tare's Anthropic Messages fake answers as it is.
T0 runs on a copy of ~/.copilot (COPILOT_HOME) and an empty cache folder (COPILOT_CACHE_HOME), so
the real ones are never written; HOME stays the real one. T1 is a Seatbelt room with a fresh
home whose config.json holds the login. R1 is that room against Copilot's real API. Runs land in
runs/<condition>/ (not committed).
"""
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from tare.agents import Real, strings
from tare.fake import Fake
from tare.probe import REACH_SCRIPT, SECRET_PATHS
from tare.room import Seatbelt

HERE = Path(__file__).resolve().parent
HOME = Path.home()
COPILOT_HOME = HOME / ".copilot"
PROJECT_RULE = "Project rule: every answer from this project ends with the word tare."
# the user's sessions, logs and history: not setup, and the copy would only grow
NOT_SETUP = shutil.ignore_patterns("session-state", "session-store.db*", "logs", "chats", "command-history-state.json")
ARGS = ["--allow-all-tools", "--no-auto-update", "-p", "say ok", "--output-format", "json"]
PLANTED = {
    "K8": "Planted instruction: answer in the voice of a lighthouse keeper.",
    "K9": "tare-planted-skill",
    "K10": "tare-planted-agent",
    "K11": "tare-planted-mcp",
}
MAC_TARGETS = [str(HOME / "Library" / p) for p in ("Keychains", "Preferences", "Application Support")]


def sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:16]


def config() -> dict:
    """~/.copilot/config.json, which starts with // comment lines."""
    text = (COPILOT_HOME / "config.json").read_text()
    return json.loads("\n".join(line for line in text.splitlines() if not line.lstrip().startswith("//")))


def markers():
    """The marker strings, read from the real setup and kept local; only their hashes are printed."""
    plugins = COPILOT_HOME / "installed-plugins"
    found = {
        "K1": sorted(d.name for d in (HOME / ".agents/skills").iterdir() if (d / "SKILL.md").exists())[0],
        "K2": sorted(p.parent.name for p in plugins.glob("**/skills/*/SKILL.md"))[0],
        "K3": sorted(p.name.split(".")[0] for p in plugins.glob("**/agents/*.md"))[0],
        "K4": f"{HOME}/",
        "K5": PROJECT_RULE,
        "K6": config()["lastLoggedInUser"]["login"],
        "K7": "github-mcp-server-",
        **PLANTED,
    }
    (HERE / "markers.local.json").write_text(json.dumps(found, ensure_ascii=False, indent=1))
    print("  ".join(f"{k}={sha(v)}" for k, v in found.items()))


def fingerprint(*roots: Path) -> str:
    """Paths, sizes and mtimes under the roots, as one digest."""
    lines = []
    for root in roots:
        for path in sorted(root.rglob("*")):
            try:
                st = path.lstat()
            except OSError:
                continue
            lines.append(f"{path} {st.st_size} {st.st_mtime_ns}")
    return sha("\n".join(lines))


def plant(copy: Path):
    """T2's markers, written into the copy of ~/.copilot only."""
    (copy / "copilot-instructions.md").write_text(PLANTED["K8"] + "\n")
    skill = copy / "skills" / PLANTED["K9"]
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text(f"---\nname: {PLANTED['K9']}\ndescription: A skill planted by tare's dirty-twin test.\n---\nDo nothing.\n")
    (copy / "agents").mkdir()
    (copy / "agents" / f"{PLANTED['K10']}.agent.md").write_text(
        f"---\nname: {PLANTED['K10']}\ndescription: An agent planted by tare's dirty-twin test.\n---\nDo nothing.\n")
    qmd = shutil.which("qmd")
    servers = {PLANTED["K11"]: {"type": "local", "command": qmd, "args": ["mcp"], "tools": ["*"]}} if qmd else {}
    (copy / "mcp-config.json").write_text(json.dumps({"mcpServers": servers}))


def gh_token(login: str) -> str:
    """The gh CLI's token for Copilot's own login: Copilot takes `gh auth token` too. Never printed."""
    token = subprocess.run(["gh", "auth", "token", "-u", login], capture_output=True, text=True).stdout.strip()
    if not token:
        sys.exit(f"gh has no token for {login}")
    return token


class Stand:
    """A stand-in adapter for the room: the binary, and a config.json with the login."""

    name, config_dir, credentials = "copilot", ".copilot", "config.json"

    def __init__(self, user: dict, token: str):
        self.user, self.token = user, token

    def token_lifetime(self, real):
        return float("inf")

    def binds(self, real):
        return ["--ro-bind", str(real.binary), "/opt/agent/copilot"], "/opt/agent/copilot"

    def seed(self, real, config_dir, room):
        login = {"lastLoggedInUser": self.user, "loggedInUsers": [{**self.user, "kind": "githubDotCom"}],
                 "copilotTokens": {f"{self.user['host']}:{self.user['login']}": self.token}}
        (config_dir / "config.json").write_text(json.dumps(login))
        (config_dir / "config.json").chmod(0o600)

    def room_env(self, room):
        return {}


def save(out: Path, proc, bodies, secret: str = ""):
    clean = (lambda s: s.replace(secret, "<token>")) if secret else (lambda s: s)
    (out / "stdout.jsonl").write_text(clean(proc.stdout))
    (out / "stderr.log").write_text(clean(proc.stderr))
    (out / "exit").write_text(str(proc.returncode))
    (out / "bodies.json").write_text(json.dumps(bodies, ensure_ascii=False))
    print(f"exit {proc.returncode}, {len(bodies)} model requests")


def run(condition: str):
    out = HERE / "runs" / condition
    out.mkdir(parents=True, exist_ok=True)
    binary = Path(shutil.which("copilot")).resolve()
    real = Real(HOME, COPILOT_HOME, binary)
    work = Path(tempfile.mkdtemp(prefix=".tare-copilot-twin-work-", dir=HOME))
    try:
        (work / "AGENTS.md").write_text(PROJECT_RULE + "\n")
        with Fake() as fake:
            byok = {"COPILOT_PROVIDER_BASE_URL": fake.url, "COPILOT_PROVIDER_TYPE": "anthropic", "COPILOT_MODEL": "tare-fake"}
            if condition in ("t0", "t0off", "t2"):
                before = fingerprint(COPILOT_HOME, HOME / ".agents")
                with tempfile.TemporaryDirectory(prefix="tare-copilot-twin-") as tmp:
                    copy, cache = Path(tmp) / "copilot", Path(tmp) / "cache"
                    shutil.copytree(COPILOT_HOME, copy, symlinks=True, ignore=NOT_SETUP)
                    cache.mkdir()
                    if condition == "t2":
                        plant(copy)
                    env = {k: v for k, v in os.environ.items() if not k.startswith("CLAUDE")} | byok | {
                        "COPILOT_HOME": str(copy), "COPILOT_CACHE_HOME": str(cache)}
                    if condition == "t0off":
                        env["COPILOT_OFFLINE"] = "true"
                    proc = subprocess.run([str(binary), *ARGS], cwd=work, env=env, capture_output=True, text=True,
                                          timeout=300, stdin=subprocess.DEVNULL)
                after = fingerprint(COPILOT_HOME, HOME / ".agents")
                (out / "fingerprint.txt").write_text(f"before {before}\nafter  {after}\n")
                print("~/.copilot and ~/.agents", "unchanged" if before == after else "CHANGED")
                save(out, proc, fake.requests)
            else:
                user = config()["lastLoggedInUser"]
                token = gh_token(user["login"])
                stand, rooms = Stand(user, token), Seatbelt()
                flags = ["--disable-builtin-mcps"] if condition == "t1f" else []
                with rooms.open(stand, real, work) as room:
                    env = {} if condition == "r1" else byok
                    args = ["--allow-all-tools", "--no-auto-update", "-p", "Reply with the single word ok.",
                            "--output-format", "json"] if condition == "r1" else ARGS
                    proc = subprocess.run(rooms.argv(room, stand, real, ["copilot", *flags, *args], env),
                                          capture_output=True, text=True, timeout=300, stdin=subprocess.DEVNULL)
                    targets = [str(real.home), str(real.config), *(str(real.home / p) for p in SECRET_PATHS), *MAC_TARGETS]
                    reach = subprocess.run(rooms.argv(room, stand, real, ["/bin/sh", "-c", REACH_SCRIPT, "reach", *targets]),
                                           capture_output=True, text=True, timeout=60)
                    (out / "reach.txt").write_text(reach.stdout)
                save(out, proc, fake.requests, token)
    finally:
        shutil.rmtree(work, ignore_errors=True)


def text_of(condition: str) -> tuple[str, set[str]]:
    bodies = [b for b in json.loads((HERE / "runs" / condition / "bodies.json").read_text()) if b.get("tools")]
    if not bodies:
        return "", set()
    main = bodies[0]
    return "\n".join(strings({k: main.get(k) for k in ("system", "messages", "tools")})), {t["name"] for t in main["tools"]}


def check():
    found = json.loads((HERE / "markers.local.json").read_text())
    for c in ("t0", "t0off", "t1", "t1f", "t2", "r1"):
        out = HERE / "runs" / c
        if not (out / "exit").exists():
            continue
        text, tools = text_of(c)
        stream = (out / "stdout.jsonl").read_text()
        print(f"== {c} (exit {(out / 'exit').read_text()}): {len(text)} chars, {len(tools)} tools")
        print("   markers:", "  ".join(f"{k}={'YES' if v in text or any(n.startswith(v) for n in tools) else 'no'}"
                                      for k, v in found.items()))
        if c == "r1":
            answer = [json.loads(l)["data"].get("content") for l in stream.splitlines()
                      if l.startswith("{") and json.loads(l).get("type") == "assistant.message"]
            print("   answer:", answer[-1:] or "none")
        for name in ("fingerprint.txt", "reach.txt"):
            if (out / name).exists():
                print(f"   {name[:-4]}:", " ".join((out / name).read_text().split()) or "nothing")


if __name__ == "__main__":
    {"markers": markers, "check": check}.get(sys.argv[1], lambda: run(sys.argv[2]))()
