"""tare probe: measure the room before the run (CONCEPT.md, layer 3).

Three readings, none of which asks the agent anything:

- context: the real CLI runs inside the room against a fake model endpoint, which
  keeps the request, i.e. the context the harness actually assembled;
- control: the same run in the user's real setup (the dirty twin). The probe must find
  the user's context there, or it is blind for that class;
- reach: a plain script inside the room looks for the user's files and inherited
  environment variables; the same script outside is its control.
"""
import json
import os
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from .fake import Fake
from .room import ROOM_CONFIG, ROOM_FLAGS, Real, TareError, bwrap, room_env, room_home

PROMPT = "say ok"
PROBE_FLAGS = ["-p", "--output-format", "stream-json", "--verbose", "--no-session-persistence"]
SECRET_PATHS = (".claude", ".claude.json", ".codex", ".config/gh", ".ssh", ".aws", ".netrc",
                ".git-credentials", ".docker/config.json")
REACH_SCRIPT = ('for p in "$@"; do if [ -e "$p" ]; then echo "path $p"; fi; done; '
                'env | cut -d= -f1 | sed "s/^/env /"')
SHELL_ENV = {"PWD", "OLDPWD", "SHLVL", "_"}
# An offered MCP tool: an entry of the tools array, or a whole line of the deferred-tools
# listing (tool search). A mention inside prose, e.g. in instructions, is not one.
MCP_TOOL = re.compile(r"^(mcp__[A-Za-z0-9_.\-]+?__)[A-Za-z0-9_.\-]+$", re.M)


@dataclass
class Finding:
    kind: str
    what: str
    source: str


@dataclass
class Capture:
    text: str  # every string of the first main-loop request
    tools: set[str]
    init: dict  # the CLI's system/init event


@dataclass
class Reading:
    version: str = "?"
    leaks: list[Finding] = field(default_factory=list)
    declared: list[Finding] = field(default_factory=list)
    seen: list[str] = field(default_factory=list)  # classes the control found in the dirty twin
    blind: list[str] = field(default_factory=list)  # classes the user has but the dirty twin did not show

    @property
    def zero(self) -> bool:
        return not self.leaks and not self.blind


def _strings(obj):
    if isinstance(obj, str):
        yield obj
    elif isinstance(obj, dict):
        for value in obj.values():
            yield from _strings(value)
    elif isinstance(obj, list):
        for value in obj:
            yield from _strings(value)


def _events(stdout: str):
    for line in stdout.splitlines():
        try:
            yield json.loads(line)
        except ValueError:
            continue


def _capture(argv: list[str], env: dict[str, str], cwd: Path, fake: Fake) -> Capture:
    proc = subprocess.run(argv, env=env, cwd=cwd, capture_output=True, text=True, timeout=300,
                          stdin=subprocess.DEVNULL)
    events = list(_events(proc.stdout))
    init = next((e for e in events if e.get("type") == "system" and e.get("subtype") == "init"), None)
    main = next((r for r in fake.requests if r.get("tools")), None)
    if init is None or main is None:
        result = next((e.get("result") for e in events if e.get("type") == "result"), None)
        detail = result or proc.stderr.strip()[-300:] or "no output"
        raise TareError(f"the CLI never reached the fake endpoint (exit {proc.returncode}): {detail}")
    text = "\n".join(_strings({k: main.get(k) for k in ("system", "messages", "tools")}))
    return Capture(text, {t["name"] for t in main["tools"]}, init)


def instruction_lines(path: Path) -> list[str]:
    """Distinctive lines of the user's global instructions, used as markers."""
    try:
        lines = [line.strip() for line in path.read_text().splitlines()]
    except OSError:
        return []
    return [line[:80] for line in lines if len(line) >= 30][:5]


def _mcp_prefixes(capture: Capture) -> set[str]:
    return set(MCP_TOOL.findall(capture.text + "\n" + "\n".join(capture.tools)))


def _server_prefix(name: str) -> str:
    return "mcp__" + re.sub(r"[^A-Za-z0-9_-]", "_", name) + "__"


def score(real: Real, twin: Capture, room: Capture, reach_in: str, reach_out: str) -> Reading:
    r = Reading(version=room.init.get("claude_code_version", "?"))

    # global instructions
    lines = instruction_lines(real.config / "CLAUDE.md")
    if lines:
        (r.seen if any(line in twin.text for line in lines) else r.blind).append("instructions")
        if any(line in room.text for line in lines):
            r.leaks.append(Finding("instructions", "global instructions", str(real.config / "CLAUDE.md")))

    # the real home path: memory paths, parent-directory instruction files, hook output
    home = f"{real.home}/"
    if home in twin.text:
        r.seen.append("home path")
    if home in room.text:
        r.leaks.append(Finding("home path", home, "the user's files"))

    # MCP servers and claude.ai connectors
    twin_servers = _mcp_prefixes(twin)
    connected = [s["name"] for s in twin.init.get("mcp_servers", []) if s.get("status") == "connected"]
    if any(_server_prefix(name) not in twin_servers for name in connected):
        r.blind.append("mcp")
    elif twin_servers:
        r.seen.append("mcp")
    for prefix in sorted(_mcp_prefixes(room)):
        source = "login (claude.ai connector)" if prefix.startswith("mcp__claude_ai_") else "MCP server"
        r.leaks.append(Finding("mcp", prefix[5:-2], source))

    # skills from plugins, the user's skills directory and the account
    plugins = twin.init.get("plugins", [])
    builtin = {p["name"] for p in plugins if p.get("path") == "builtin"}
    user_plugins = {p["name"] for p in plugins if p.get("path") != "builtin"}
    skill_dir = real.config / "skills"
    own = {d.name for d in skill_dir.iterdir() if d.is_dir()} if skill_dir.is_dir() else set()
    names = {s for s in twin.init.get("skills", []) if ":" in s and s.split(":")[0] not in builtin} | own
    listed = {}
    for name in sorted(names):
        # the skills listing has one "- name: description" line per skill
        match = re.search(rf"^- {re.escape(name)}(?::.*)?$", twin.text, re.M)
        if match:
            namespace = name.split(":")[0] if ":" in name else None
            source = (str(skill_dir) if namespace is None
                      else f"plugin {namespace}" if namespace in user_plugins else "login (account skills)")
            listed[match.group(0)[:160]] = source
    if names:
        (r.seen if listed else r.blind).append("skills")
    counts: dict[str, int] = {}
    for line, source in listed.items():
        if line in room.text:
            counts[source] = counts.get(source, 0) + 1
    r.leaks += [Finding("skills", f"{n} skill{'s' if n != 1 else ''}", source) for source, n in sorted(counts.items())]
    if user_plugins:
        r.seen.append("plugins")
    r.leaks += [Finding("plugin", p["name"], p.get("path", "?"))
                for p in room.init.get("plugins", []) if p.get("path") != "builtin"]

    # the account email comes with subscription auth: declared, not a leak
    email = real.email()
    if email and email in twin.text:
        r.seen.append("email")
        if email in room.text:
            r.declared.append(Finding("email", "account email", "subscription login"))

    # reach: the same script outside (control) and inside the room
    if any(line.startswith("path ") for line in reach_out.splitlines()):
        r.seen.append("reach")
    allowed = set(room_env({})) | SHELL_ENV
    for line in reach_in.splitlines():
        kind, _, value = line.partition(" ")
        if kind == "path":
            r.leaks.append(Finding("reach", value, "visible inside the room"))
        elif kind == "env" and value not in allowed:
            r.leaks.append(Finding("env", value, "inherited environment"))
    r.declared.append(Finding("credentials", f"{ROOM_CONFIG}/.credentials.json", "copy of the login, needed by the CLI"))
    return r


def probe(real: Real, project: Path) -> Reading:
    project = project.resolve()
    targets = [str(real.home), str(real.config), *(str(real.home / p) for p in SECRET_PATHS)]
    if Path("/mnt/c").is_dir():
        targets.append("/mnt/c")  # WSL: the Windows drive and its user profile

    # the dirty twin: the user's real setup, as a plain terminal would start it
    twin_env = {k: v for k, v in os.environ.items() if not k.startswith("CLAUDE") or k == "CLAUDE_CONFIG_DIR"}
    with Fake() as fake:
        twin_env |= {"ANTHROPIC_BASE_URL": fake.url, "ENABLE_TOOL_SEARCH": "true"}
        twin = _capture([str(real.claude), *PROBE_FLAGS, PROMPT], twin_env, project, fake)

    with room_home(real) as home:
        with Fake() as fake:
            argv = bwrap(home, project, real.claude, ["claude", *ROOM_FLAGS, *PROBE_FLAGS, PROMPT],
                         {"ANTHROPIC_BASE_URL": fake.url})
            room = _capture(argv, {**os.environ}, project, fake)
        reach = ["/bin/sh", "-c", REACH_SCRIPT, "reach", *targets]
        reach_in = subprocess.run(bwrap(home, project, real.claude, reach), capture_output=True, text=True,
                                  timeout=60, check=True).stdout
    reach_out = subprocess.run(reach, capture_output=True, text=True, timeout=60, check=True).stdout
    return score(real, twin, room, reach_in, reach_out)


def render(reading: Reading, project: Path) -> str:
    width = max((len(f.what) for f in reading.leaks + reading.declared), default=0) + 2

    def rows(findings):
        return [f"    {f.kind:<13}{f.what:<{width}}{f.source}" for f in findings]

    out = [f"tare probe · claude {reading.version} · {project}",
           f"  control   dirty twin shows: {', '.join(reading.seen) or 'nothing'}"]
    for cls in reading.blind:
        out.append(f"  BLIND     {cls}: the user has it, but the dirty twin did not show it")
    if reading.leaks:
        out += ["  leaks", *rows(reading.leaks)]
    else:
        out.append("  leaks     none")
    if reading.declared:
        out += ["  declared", *rows(reading.declared)]
    if reading.zero:
        out.append("tare: 0.00")
    elif reading.leaks:
        out.append(f"tare: {len(reading.leaks)} leak{'s' if len(reading.leaks) != 1 else ''}")
    else:
        out.append("tare: not proven (blind)")
    return "\n".join(out)
