"""tare probe: measure the room before the run (CONCEPT.md, layer 3).

Three readings, none of which asks the agent anything:

- context: the real CLI runs inside the room against a fake model endpoint, which
  keeps the request, i.e. the context the harness actually assembled;
- control: the same run in the user's real setup (the dirty twin). The probe must find
  the user's context there, or it is blind for that class;
- reach: a plain script inside the room looks for the user's files and inherited
  environment variables; the same script outside is its control.
"""
import os
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from .agents import Capture, Real
from .fake import Fake
from .room import TareError, bwrap, room_env, room_home

SECRET_PATHS = (".claude", ".claude.json", ".codex", ".agents", ".config/gh", ".ssh", ".aws", ".netrc",
                ".git-credentials", ".docker/config.json")
REACH_SCRIPT = ('for p in "$@"; do if [ -e "$p" ]; then echo "path $p"; fi; done; '
                'env | cut -d= -f1 | sed "s/^/env /"')
SHELL_ENV = {"PWD", "OLDPWD", "SHLVL", "_"}
LABELS = {"instructions": "global instructions", "memories": "memories"}
# An offered MCP tool: an entry of the tools array, or a whole line of a deferred-tools
# listing (tool search). A mention inside prose, e.g. in instructions, is not one.
MCP_TOOL = re.compile(r"^(mcp__[A-Za-z0-9_.\-]+?__)[A-Za-z0-9_.\-]+$", re.M)


@dataclass
class Finding:
    kind: str
    what: str
    source: str


@dataclass
class Reading:
    agent: str = "?"
    version: str = "?"
    leaks: list[Finding] = field(default_factory=list)
    declared: list[Finding] = field(default_factory=list)
    seen: list[str] = field(default_factory=list)  # classes the control found in the dirty twin
    blind: list[str] = field(default_factory=list)  # classes the user has but the dirty twin did not show

    @property
    def zero(self) -> bool:
        return not self.leaks and not self.blind


def _capture(agent, argv: list[str], env: dict[str, str], cwd: Path, fake: Fake) -> Capture:
    proc = subprocess.run(argv, env=env, cwd=cwd, capture_output=True, text=True, timeout=300,
                          stdin=subprocess.DEVNULL)
    capture = agent.capture(proc.stdout, fake.requests)
    if capture is None:
        detail = proc.stderr.strip()[-300:] or proc.stdout.strip()[-300:] or "no output"
        raise TareError(f"{agent.name} never reached the fake endpoint (exit {proc.returncode}): {detail}")
    return capture


def instruction_lines(path: Path) -> list[str]:
    """Distinctive lines of a file of the user's, used as markers."""
    try:
        lines = [line.strip() for line in path.read_text().splitlines()]
    except OSError:
        return []
    return [line[:80] for line in lines if len(line) >= 30][:5]


def _mcp_prefixes(capture: Capture) -> set[str]:
    return set(MCP_TOOL.findall(capture.text + "\n" + "\n".join(capture.tools)))


def _server_prefix(name: str) -> str:
    return "mcp__" + re.sub(r"[^A-Za-z0-9_-]", "_", name) + "__"


def score(agent, real: Real, twin: Capture, room: Capture, reach_in: str, reach_out: str) -> Reading:
    r = Reading(agent=agent.name, version=room.init.get("claude_code_version", "?"))

    # the user's own files: global instructions, and whatever else the agent reads (memories)
    for kind, path in [("instructions", agent.instructions(real)), *agent.extra_markers(real)]:
        lines = instruction_lines(path)
        if lines:
            (r.seen if any(line in twin.text for line in lines) else r.blind).append(kind)
            if any(line in room.text for line in lines):
                r.leaks.append(Finding(kind, LABELS.get(kind, kind), str(path)))

    # the real home path: memory paths, parent-directory instruction files, hook output
    home = f"{real.home}/"
    if home in twin.text:
        r.seen.append("home path")
    if home in room.text:
        r.leaks.append(Finding("home path", home, "the user's files"))

    # MCP servers and connectors
    twin_servers = _mcp_prefixes(twin)
    connected = [s["name"] for s in twin.init.get("mcp_servers", []) if s.get("status") == "connected"]
    if any(_server_prefix(name) not in twin_servers for name in connected):
        r.blind.append("mcp")
    elif twin_servers:
        r.seen.append("mcp")
    for prefix in sorted(_mcp_prefixes(room)):
        source = "login (claude.ai connector)" if prefix.startswith("mcp__claude_ai_") else "MCP server"
        r.leaks.append(Finding("mcp", prefix[5:-2], source))

    # skills from plugins, the user's skill directories and the account
    plugins = twin.init.get("plugins", [])
    builtin = {p["name"] for p in plugins if p.get("path") == "builtin"}
    user_plugins = {p["name"] for p in plugins if p.get("path") != "builtin"}
    own: dict[str, Path] = {}
    for skill_dir in agent.skill_dirs(real):
        if skill_dir.is_dir():
            own |= {d.name: skill_dir for d in skill_dir.iterdir() if d.is_dir() and not d.name.startswith(".")}
    names = {s for s in twin.init.get("skills", []) if ":" in s and s.split(":")[0] not in builtin} | set(own)
    listed = {}
    for name in sorted(names):
        # the skills listing has one "- name: description" line per skill
        match = re.search(rf"^- {re.escape(name)}(?::.*)?$", twin.text, re.M)
        if match:
            namespace = name.split(":")[0] if ":" in name else None
            source = (str(own[name]) if namespace is None
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
    email = agent.email(real)
    if email and email in twin.text:
        r.seen.append("email")
        if email in room.text:
            r.declared.append(Finding("email", "account email", "subscription login"))

    # reach: the same script outside (control) and inside the room
    if any(line.startswith("path ") for line in reach_out.splitlines()):
        r.seen.append("reach")
    allowed = set(room_env(agent)) | SHELL_ENV
    for line in reach_in.splitlines():
        kind, _, value = line.partition(" ")
        if kind == "path":
            r.leaks.append(Finding("reach", value, "visible inside the room"))
        elif kind == "env" and value not in allowed:
            r.leaks.append(Finding("env", value, "inherited environment"))
    r.declared.append(Finding("credentials", f"{agent.room_config}/{agent.credentials}",
                              "copy of the login, needed by the CLI"))
    return r


def probe(agent, real: Real, project: Path) -> Reading:
    project = project.resolve()
    targets = [str(real.home), str(real.config), *(str(real.home / p) for p in SECRET_PATHS)]
    if Path("/mnt/c").is_dir():
        targets.append("/mnt/c")  # WSL: the Windows drive and its user profile

    # the dirty twin: the user's real setup, as a plain terminal would start it
    twin_env = {k: v for k, v in os.environ.items() if not k.startswith("CLAUDE") or k == "CLAUDE_CONFIG_DIR"}
    with Fake() as fake:
        args, env = agent.probe(fake.url)
        twin = _capture(agent, [str(real.binary), *args], twin_env | env, project, fake)

    with room_home(agent, real) as home:
        with Fake() as fake:
            args, env = agent.probe(fake.url)
            argv = bwrap(agent, real, home, project, [agent.name, *agent.room_flags, *args], env)
            room = _capture(agent, argv, {**os.environ}, project, fake)
        reach = ["/bin/sh", "-c", REACH_SCRIPT, "reach", *targets]
        reach_in = subprocess.run(bwrap(agent, real, home, project, reach), capture_output=True, text=True,
                                  timeout=60, check=True).stdout
    reach_out = subprocess.run(reach, capture_output=True, text=True, timeout=60, check=True).stdout
    return score(agent, real, twin, room, reach_in, reach_out)


def render(reading: Reading, project: Path) -> str:
    width = max((len(f.what) for f in reading.leaks + reading.declared), default=0) + 2

    def rows(findings):
        return [f"    {f.kind:<13}{f.what:<{width}}{f.source}" for f in findings]

    version = f" {reading.version}" if reading.version != "?" else ""
    out = [f"tare probe · {reading.agent}{version} · {project}",
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
