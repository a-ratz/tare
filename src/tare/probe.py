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
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

from .agents import Capture, Real
from .fake import Fake
from .room import Room, TareError, _user_dir, backend, room_env

SECRET_PATHS = (".claude", ".claude.json", ".codex", ".agents", ".config/gh", ".ssh", ".aws", ".netrc",
                ".git-credentials", ".docker/config.json")
REACH_SCRIPT = ('for p in "$@"; do if [ -e "$p" ]; then echo "path $p"; fi; done; '
                'env | cut -d= -f1 | sed "s/^/env /"')
# macOS: the pasteboard holds whatever the user copied last; it is not a path, but reads like one
PASTEBOARD = '; if pbpaste >/dev/null 2>&1; then echo "path pasteboard"; fi'
SHELL_ENV = {"PWD", "OLDPWD", "SHLVL", "_"}
LABELS = {"instructions": "global instructions", "memories": "memories"}
# An offered MCP tool: an entry of the tools array, or a whole line of a deferred-tools
# listing (tool search). A mention inside prose, e.g. in instructions, is not one.
MCP_TOOL = re.compile(r"^(mcp__[A-Za-z0-9_.\-]+?__)[A-Za-z0-9_.\-]+$", re.M)
# Under load a dirty twin can send its request before its MCP servers are connected. A blind
# twin gets one more try after this pause, and the reading says so.
TWIN_RETRY_PAUSE = 10


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
    retried: list[str] = field(default_factory=list)  # classes a first dirty twin was blind for

    @property
    def zero(self) -> bool:
        return not self.leaks and not self.blind


def _capture(agent, argv: list[str], env: dict[str, str], cwd: Path, fake: Fake) -> Capture:
    proc = subprocess.run(argv, env=env, cwd=cwd, capture_output=True, text=True, timeout=300,
                          stdin=subprocess.DEVNULL)
    capture = agent.capture(proc.stdout, fake.requests)
    if capture is None:
        detail = proc.stderr.strip()[-300:] or proc.stdout.strip()[-300:] or "no output"
        raise TareError(f"{agent.name} never reached tare's fake model server, so the probe could not run "
                        f"(exit {proc.returncode}): {detail}")
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


def _without_paths(text: str) -> str:
    """Skill lines with their "(path)" removed: agy names each skill's file, and the room's
    path (/home/tare/...) differs from the user's for the same skill."""
    return re.sub(r" \([^)\n]*\)", "", text)


def _skill_entry(text: str, name: str) -> str | None:
    """How a request lists one skill: a "- name: description" line (agy writes "- name (path): ..."),
    or a <skill> element with name, description and location (Pi). Paths are left out, because the
    room's differ from the user's for the same skill."""
    line = re.search(rf"^- {re.escape(name)}(?:[:( ].*)?$", text, re.M)
    if line:
        return _without_paths(line.group(0))[:160]
    escaped = name.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    element = re.search(rf"<skill>\s*<name>{re.escape(escaped)}</name>(.*?)</skill>", text, re.S)
    if element:
        inner = re.sub(r"<location>.*?</location>", "", element.group(1), flags=re.S)
        return f"<skill> {name}: {' '.join(inner.split())}"[:160]
    return None


def _server_prefix(name: str) -> str:
    return "mcp__" + re.sub(r"[^A-Za-z0-9_-]", "_", name) + "__"


def parent_instructions(project: Path) -> list[Path]:
    """Instruction files in the project's parent directories: the user's, not the project's."""
    return [d / name for d in project.parents for name in ("AGENTS.md", "CLAUDE.md") if (d / name).is_file()]


def score(agent, real: Real, twin: Capture, room: Capture, reach_in: str, reach_out: str,
          bare: Capture | None = None, project: Path | None = None, built: Room | None = None) -> Reading:
    """`built` is the Room the room's capture ran in; its backend adds variables of its own."""
    r = Reading(agent=agent.name, version=room.init.get("claude_code_version", "?"))

    # instruction files above the project; an agent that does not read them cannot leak them
    for path in parent_instructions(project) if project else []:
        lines = instruction_lines(path)
        if lines and any(line in twin.text for line in lines):
            if "parent files" not in r.seen:
                r.seen.append("parent files")
            if any(line in room.text for line in lines):
                r.leaks.append(Finding("parent files", "instructions above the project", str(path)))

    # extensions: tools the dirty twin offers that a run without extensions does not
    if bare is not None:
        extension_tools = twin.tools - bare.tools
        if extension_tools:
            r.seen.append("extensions")
        r.leaks += [Finding("extensions", name, "a tool of your extensions") for name in sorted(extension_tools & room.tools)]

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
        r.leaks.append(Finding("home path", home, "your files"))

    # MCP servers and connectors
    twin_servers = _mcp_prefixes(twin)
    connected = [s["name"] for s in twin.init.get("mcp_servers", []) if s.get("status") == "connected"]
    if any(_server_prefix(name) not in twin_servers for name in connected):
        r.blind.append("mcp")
    elif twin_servers:
        r.seen.append("mcp")
    for prefix in sorted(_mcp_prefixes(room)):
        source = "connected account (login)" if prefix.startswith("mcp__claude_ai_") else "MCP server"
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
    listed: dict[str, tuple[str, str]] = {}  # skill name -> how the twin lists it, and its source
    for name in sorted(names):
        entry = _skill_entry(twin.text, name)
        if entry:
            namespace = name.split(":")[0] if ":" in name else None
            source = (str(own[name]) if namespace is None
                      else f"plugin {namespace}" if namespace in user_plugins else "login (account skills)")
            listed[name] = (entry, source)
    if names:
        (r.seen if listed else r.blind).append("skills")
    counts: dict[str, int] = {}
    for name, (entry, source) in listed.items():
        if _skill_entry(room.text, name) == entry:
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
    allowed = set(room_env(agent, built)) | SHELL_ENV
    for line in reach_in.splitlines():
        kind, _, value = line.partition(" ")
        if kind == "path":
            r.leaks.append(Finding("reach", value, "visible inside the room"))
        elif kind == "env" and value not in allowed:
            r.leaks.append(Finding("env", value, "inherited environment"))
    for name in getattr(agent, "secret_files", [agent.credentials]):
        config = (built or Room(Path(), Path())).inside_config(agent)
        r.declared.append(Finding("credentials", f"{config}/{name}", "copy of the login, needed by the CLI"))
    return r


def settle(run_twin, read) -> Reading:
    """Read with a dirty twin; a twin blind for some class gets one more try."""
    reading = read(run_twin())
    if reading.blind:
        first = list(reading.blind)
        time.sleep(TWIN_RETRY_PAUSE)
        reading = read(run_twin())
        reading.retried = first
    return reading


def reach(real: Real) -> list[str]:
    """The reach script and the places it looks for."""
    targets = [str(real.home), str(real.config), *(str(real.home / p) for p in SECRET_PATHS)]
    script = REACH_SCRIPT
    if Path("/mnt/c").is_dir():
        targets.append("/mnt/c")  # WSL: the Windows drive and its user profile
    if sys.platform == "darwin":
        # where macOS keeps what a room must not reach (experiments/dirty-twin-macos)
        targets += [str(real.home / "Library" / p) for p in ("Keychains", "Preferences", "Application Support")]
        targets += [str(_user_dir()), f"/private/tmp/claude-{os.getuid()}", "/private/var/tmp", "/Users/Shared"]
        script += PASTEBOARD
    return ["/bin/sh", "-c", script, "reach", *targets]


def probe(agent, real: Real, project: Path) -> Reading:
    project = project.resolve()

    # the dirty twin: the user's real setup, as a plain terminal would start it
    twin_env = {k: v for k, v in os.environ.items() if not k.startswith("CLAUDE") or k == "CLAUDE_CONFIG_DIR"}

    def run_twin() -> Capture:
        with Fake() as fake:
            args, env = agent.probe(fake.url)
            with agent.twin(real, fake.url) as extra:
                env = twin_env | env | extra
                argv = [str(real.binary), *args]
                if hasattr(agent, "twin_argv"):  # a twin that must not write into the real setup
                    argv = agent.twin_argv(argv, env)
                return _capture(agent, argv, env, project, fake)

    rooms = backend()

    def in_room(room: Room, flags: list[str]) -> Capture:
        with Fake() as fake:
            agent.prepare_probe(room.config(agent), fake.url)
            args, env = agent.probe(fake.url)
            argv = rooms.argv(room, agent, real, [agent.name, *flags, *args], env)
            return _capture(agent, argv, {**os.environ}, project, fake)

    with rooms.open(agent, real, project) as room:
        inside = in_room(room, agent.room_flags)
        # where an agent loads extensions, a run without them shows which tools are its own
        bare = in_room(room, [*agent.room_flags, *agent.bare_flags]) if getattr(agent, "bare_flags", None) else None
        reach_in = subprocess.run(rooms.argv(room, agent, real, reach(real)), capture_output=True, text=True,
                                  timeout=60, check=True).stdout
    reach_out = subprocess.run(reach(real), capture_output=True, text=True, timeout=60, check=True).stdout
    return settle(run_twin, lambda twin: score(agent, real, twin, inside, reach_in, reach_out, bare=bare,
                                                project=project, built=room))


def render(reading: Reading, project: Path) -> str:
    width = max((len(f.what) for f in reading.leaks + reading.declared), default=0) + 2

    def rows(findings):
        return [f"    {f.kind:<13}{f.what:<{width}}{f.source}" for f in findings]

    version = f" {reading.version}" if reading.version != "?" else ""
    out = [f"tare probe · {reading.agent}{version} · {project}",
           f"  control   dirty twin shows: {', '.join(reading.seen) or 'nothing'}"]
    if reading.retried:
        out.append(f"  retried   the first dirty twin was blind for {', '.join(reading.retried)}. "
                   "This reading comes from a second one.")
    for cls in reading.blind:
        out.append(f"  BLIND     {cls}: you have it, but the dirty twin did not show it, so the room cannot be "
                   "proven clean of it")
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
