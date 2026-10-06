"""What tare has to know about each agent CLI (CONCEPT.md, "Adapters").

An adapter says where the user's real setup lives, how its login is copied into a room,
how the CLI is pointed at the fake endpoint, how the captured request is read, and which
of the user's files mark their context.
"""
import base64
import getpass
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import tomllib
import unicodedata
from contextlib import contextmanager, nullcontext
from dataclasses import dataclass
from pathlib import Path

from . import trail as trails
from .fake import FAKE_MODEL
from .room import TareError
from .usage import Usage

PROMPT = "say ok"


@dataclass(frozen=True)
class Real:
    """The user's real setup for one agent, outside the room."""

    home: Path
    config: Path  # the agent's config directory (~/.claude, ~/.codex)
    binary: Path  # the CLI, resolved


@dataclass
class Capture:
    text: str  # every string of the first model request
    tools: set[str]
    init: dict  # the CLI's own report of what it loaded, where it gives one (Codex: what its request lists)


def strings(obj):
    if isinstance(obj, str):
        yield obj
    elif isinstance(obj, dict):
        for value in obj.values():
            yield from strings(value)
    elif isinstance(obj, list):
        for value in obj:
            yield from strings(value)


def events(stdout: str):
    for line in stdout.splitlines():
        try:
            yield json.loads(line)
        except ValueError:
            continue


def _which(name: str) -> Path:
    found = shutil.which(name)
    if not found:
        raise TareError(f"{name} is not on PATH")
    return Path(found).resolve()


def _absolute_links(original: Path, copy: Path):
    """A relative symlink copied elsewhere points nowhere (a skill linked as ../../../.agents/skills/x).
    Point each one in the copy at what the original link reaches."""
    for root, dirs, files in os.walk(copy):
        for name in dirs + files:
            link = Path(root) / name
            if link.is_symlink() and not os.path.isabs(target := os.readlink(link)):
                reached = os.path.normpath((original / link.relative_to(copy)).parent / target)
                link.unlink()
                link.symlink_to(reached)


def _json(path: Path) -> dict | None:
    """A JSON file of the agent's setup, read for its field names and flags, never printed."""
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return None


def _one_run(u: Usage) -> Usage:
    """A run's usage is summed from several events, but it is one run."""
    u.runs, u.unpriced = 1, 1 if u.cost_usd is None else 0
    return u


def _security(account: str, service: str) -> str | None:
    """A password from the user's Keychain, read the way Claude Code reads its own. Never printed."""
    found = subprocess.run(["security", "find-generic-password", "-a", account, "-w", "-s", service],
                           capture_output=True, text=True)
    return found.stdout.rstrip("\n") if found.returncode == 0 else None


def _lifetime_error(path: Path) -> TareError:
    return TareError(f"no login at {path}: log in with the agent first")


class Claude:
    name = "claude"
    credentials = ".credentials.json"
    config_dir = ".claude-config"  # under the room's home
    # A Seatbelt room cannot start Claude Code's own sandbox, so a project that turns it on would
    # fail every Bash call there (measured, #90): macOS rooms turn it off.
    sandbox_off = {"sandbox": {"enabled": False}}

    @property
    def room_flags(self) -> list[str]:
        # Login-carried connectors and account skills arrive unless these are passed (CONCEPT.md, layer 1).
        flags = ["--strict-mcp-config", "--setting-sources", "project,local"]
        return flags + ["--settings", json.dumps(self.sandbox_off)] if sys.platform == "darwin" else flags
    yolo = ["--dangerously-skip-permissions"]
    native_resume = True  # Cliff resumes its own session; Swap prices handoffs against it

    def discover(self) -> Real:
        home = Path.home()
        custom = os.environ.get("CLAUDE_CONFIG_DIR")
        return Real(home, Path(custom) if custom else home / ".claude", _which("claude"))

    def state(self, real: Real) -> Path:
        # .claude.json moves with CLAUDE_CONFIG_DIR, otherwise it sits in the home directory
        return real.config / ".claude.json" if os.environ.get("CLAUDE_CONFIG_DIR") else real.home / ".claude.json"

    def keychain_item(self) -> tuple[str, str]:
        """The account and service of the Keychain item Claude Code keeps its login in on macOS. The
        service has a suffix from the config directory when CLAUDE_CONFIG_DIR is set (Claude Code 2.1.289)."""
        user = os.environ.get("USER") or getpass.getuser()
        account = user if re.fullmatch(r"[a-zA-Z0-9._-]+", user) else "claude-code-user"
        custom = os.environ.get("CLAUDE_CONFIG_DIR")
        suffix = f"-{hashlib.sha256(unicodedata.normalize('NFC', custom).encode()).hexdigest()[:8]}" if custom else ""
        return account, f"Claude Code-credentials{suffix}"

    def _keychain(self) -> str | None:
        """macOS: the login from the Keychain."""
        return _security(*self.keychain_item()) if sys.platform == "darwin" else None

    def _login(self, real: Real) -> str | None:
        """The login's JSON: the Keychain item on macOS, else (and as Claude Code's own fallback) the file."""
        keychain = self._keychain()
        if keychain is not None:
            return keychain
        try:
            return (real.config / self.credentials).read_text()
        except OSError:
            return None

    def token_lifetime(self, real: Real) -> float:
        path = real.config / self.credentials
        try:
            return json.loads(self._login(real))["claudeAiOauth"]["expiresAt"] / 1000 - time.time()
        except (ValueError, KeyError, TypeError):
            if sys.platform == "darwin":
                raise TareError(f"no login in the Keychain ({self.keychain_item()[1]}) or at {path}: "
                                "log in with the agent first") from None
            raise _lifetime_error(path) from None

    def seed(self, real: Real, config: Path, room):
        # Claude Code takes the login from this file when its room has no Keychain item (#86)
        keychain = self._keychain()
        if keychain is None:
            shutil.copyfile(real.config / self.credentials, config / self.credentials)
        else:
            (config / self.credentials).write_text(keychain)
        (config / self.credentials).chmod(0o600)
        (config / ".claude.json").write_text(json.dumps(
            {"hasCompletedOnboarding": True, "projects": {room.inside_work: {"hasTrustDialogAccepted": True}}}))

    def room_env(self, room) -> dict[str, str]:
        # A custom base URL turns tool search off; keep probe and run in the same form.
        env = {"CLAUDE_CONFIG_DIR": room.inside_config(self), "ENABLE_TOOL_SEARCH": "true"}
        if "TMPDIR" in room.env:
            env["CLAUDE_CODE_TMPDIR"] = room.env["TMPDIR"]  # it ignores TMPDIR and uses /tmp/claude-<uid> (#86)
        return env

    def binds(self, real: Real) -> tuple[list[str], str]:
        """bwrap arguments that make the CLI available, and the command inside the room."""
        return ["--ro-bind", str(real.binary), "/opt/agent/claude"], "/opt/agent/claude"

    def probe(self, fake_url: str) -> tuple[list[str], dict[str, str]]:
        """Arguments for one probe turn, and the environment that points the CLI at the fake."""
        args = ["-p", "--output-format", "stream-json", "--verbose", "--no-session-persistence", PROMPT]
        return args, {"ANTHROPIC_BASE_URL": fake_url, "ENABLE_TOOL_SEARCH": "true"}

    def twin(self, real: Real, fake_url: str):
        return nullcontext({})

    def prepare_probe(self, config: Path, fake_url: str):
        pass

    def capture(self, stdout: str, requests: list[dict]) -> Capture | None:
        init = next((e for e in events(stdout) if e.get("type") == "system" and e.get("subtype") == "init"), None)
        main = next((r for r in requests if r.get("tools")), None)
        if init is None or main is None:
            return None
        text = "\n".join(strings({k: main.get(k) for k in ("system", "messages", "tools")}))
        return Capture(text, {t["name"] for t in main["tools"]}, init)

    def instructions(self, real: Real) -> Path:
        return real.config / "CLAUDE.md"

    # unattended runs (Cliff, Swap): args after the room flags; `hook` archives /work after every tool call
    def run_args(self, prompt: str, extra: list[str], hook: str | None = None, room=None) -> list[str]:
        args = ["--dangerously-skip-permissions"]
        if hook:
            settings = {"hooks": {"PostToolUse": [{"matcher": "", "hooks": [{"type": "command", "command": hook}]}]}}
            # Claude Code takes only the last --settings (measured, 2.1.290), and this one comes after the room flags
            if sys.platform == "darwin":
                settings |= self.sandbox_off
            args += ["--settings", json.dumps(settings)]
        return args + extra + ["-p", prompt, "--output-format", "stream-json", "--verbose"]

    def prepare_hook(self, config: Path, hook: str):
        pass  # passed with --settings in run_args

    def resume_args(self, session: str, prompt: str, extra: list[str]) -> list[str] | None:
        # the same event stream as a fresh start, so a resumed tail shows what it did
        return ["--dangerously-skip-permissions", *extra, "-p", "--resume", session, prompt,
                "--output-format", "stream-json", "--verbose"]

    def session_file(self, home: Path) -> Path | None:
        sessions = sorted((home / ".claude-config" / "projects").rglob("*.jsonl"), key=lambda p: p.stat().st_size)
        return sessions[-1] if sessions else None

    def place_session(self, room, session: str, lines: list[str]):
        # Claude Code keeps a project's sessions in a directory named after its path
        target = room.config(self) / "projects" / re.sub(r"[^A-Za-z0-9]", "-", room.inside_work)
        target.mkdir(parents=True, exist_ok=True)
        (target / f"{session}.jsonl").write_text("\n".join(lines) + "\n")

    def trail(self, lines: list[str]) -> trails.Trail:
        return trails.claude(lines)

    def usage(self, stdout: str) -> Usage:
        """From the `result` events: input_tokens leaves out the cache, so the cache is added."""
        u = Usage(cost_usd=None)
        for e in events(stdout):
            if e.get("type") != "result":
                continue
            n = e.get("usage") or {}
            models = e.get("modelUsage") or {}
            top = max(models.values(), key=lambda m: m.get("costUSD") or 0, default={})
            u = u + Usage(n.get("input_tokens", 0) + n.get("cache_creation_input_tokens", 0)
                          + n.get("cache_read_input_tokens", 0), n.get("cache_read_input_tokens", 0),
                          n.get("cache_creation_input_tokens", 0), n.get("output_tokens", 0),
                          sum(m.get("thinkingTokens", 0) for m in models.values()), e.get("total_cost_usd"),
                          top.get("canonicalModel"))
        return _one_run(u)

    def activity(self, event: dict) -> str | None:
        """What one line of the live stream (stream-json) shows, for the dashboard."""
        if event.get("type") == "result":
            return "finished"
        if event.get("type") == "assistant":
            for block in reversed((event.get("message") or {}).get("content") or []):
                if block.get("type") == "tool_use":
                    args = block.get("input", {})
                    detail = args.get("command") or args.get("file_path") or args.get("pattern") or ""
                    return f"{block.get('name')}: {str(detail).splitlines()[0][:90] if detail else ''}"
                if block.get("type") == "text" and block.get("text", "").strip():
                    return "says: " + block["text"].strip().splitlines()[0][:90]
        return None

    def skill_dirs(self, real: Real) -> list[Path]:
        return [real.config / "skills"]

    def extra_markers(self, real: Real) -> list[tuple[str, Path]]:
        return []

    def email(self, real: Real) -> str | None:
        try:
            return json.loads(self.state(real).read_text())["oauthAccount"]["emailAddress"]
        except (OSError, ValueError, KeyError, TypeError):
            return None

    def billing(self, real: Real) -> str | None:
        """How the login pays: a subscription makes the reported cost notional."""
        try:
            data = json.loads(self._login(real))
        except (TypeError, ValueError):
            return None
        return "subscription" if "claudeAiOauth" in data else "api key"


# a plugin's skill in Codex's skills listing: "- <plugin>:<skill>: <description>"
PLUGIN_SKILL = re.compile(r"^- ([A-Za-z0-9_.-]+:[A-Za-z0-9_.-]+): ", re.M)


class Codex:
    name = "codex"
    credentials = "auth.json"
    config_dir = ".codex"
    # Account plugins can restore personal skills after login (CONCEPT.md, adapters).
    room_flags = ["--disable", "remote_plugin"]
    yolo = ["--dangerously-bypass-approvals-and-sandbox"]
    native_resume = True

    def discover(self) -> Real:
        home = Path.home()
        custom = os.environ.get("CODEX_HOME")
        return Real(home, Path(custom) if custom else home / ".codex", _which("codex"))

    def token_lifetime(self, real: Real) -> float:
        path = real.config / self.credentials
        try:
            auth = json.loads(path.read_text())
            if auth.get("OPENAI_API_KEY"):
                return float("inf")
            payload = auth["tokens"]["access_token"].split(".")[1]
            claims = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
            return claims["exp"] - time.time()
        except (OSError, ValueError, KeyError, IndexError, TypeError):
            raise _lifetime_error(path) from None

    def seed(self, real: Real, config: Path, room):
        shutil.copyfile(real.config / self.credentials, config / self.credentials)
        (config / self.credentials).chmod(0o600)
        (config / "config.toml").write_text(f'[projects."{room.inside_work}"]\ntrust_level = "trusted"\n')

    def room_env(self, room) -> dict[str, str]:
        return {"CODEX_HOME": room.inside_config(self)}

    def binds(self, real: Real) -> tuple[list[str], str]:
        if sys.platform == "darwin":
            # the standalone release (bin/codex beside its helpers) lives in ~/.codex/packages (#86)
            release = real.binary.parents[1]
            return ["--ro-bind", str(release), "/opt/agent/codex"], f"/opt/agent/codex/{real.binary.relative_to(release)}"
        # the npm package and node live under /usr, which every room mounts read-only
        if not real.binary.is_relative_to("/usr"):
            raise TareError(f"codex resolves to {real.binary}; tare needs a codex installed under /usr for now")
        return [], "codex"

    def probe(self, fake_url: str) -> tuple[list[str], dict[str, str]]:
        # Codex keeps its ChatGPT login against a custom openai_base_url. Uncompressed bodies,
        # so the fake can read them; that changes the transport, not the context.
        args = ["exec", "--json", "--ephemeral", "--skip-git-repo-check",
                "-c", f"openai_base_url={fake_url}/v1", "--disable", "enable_request_compression", PROMPT]
        return args, {}

    def twin(self, real: Real, fake_url: str):
        return nullcontext({})

    def prepare_probe(self, config: Path, fake_url: str):
        pass

    def capture(self, stdout: str, requests: list[dict]) -> Capture | None:
        main = next((r for r in requests if "input" in r), None)
        if main is None:
            return None
        entries = [*main.get("tools", []), *(t for item in main.get("input", []) for t in item.get("tools", []) or [])]
        tools = set()
        for t in entries:
            if isinstance(t, dict) and t.get("name"):
                tools.add(t["name"])
                if t.get("type") == "namespace" and t["name"].startswith("mcp__"):
                    # an MCP server's tools, grouped as mcp__<server>: named the way MCP names them
                    tools |= {f"{t['name']}__{n['name']}" for n in t.get("tools", [])
                              if isinstance(n, dict) and n.get("name")}
        text = "\n".join(strings({k: main.get(k) for k in ("instructions", "input", "tools")}))
        # Codex gives no init report, but its request lists each plugin's skills as
        # "- <plugin>:<skill>: ...". Those lines name the plugins and their skills.
        skills = sorted(set(PLUGIN_SKILL.findall(text)))
        plugins = sorted({s.split(":")[0] for s in skills})
        init = {"skills": skills, "plugins": [{"name": p, "path": "Codex plugin"} for p in plugins]} if skills else {}
        return Capture(text, tools, init)

    def instructions(self, real: Real) -> Path:
        return real.config / "AGENTS.md"

    def run_args(self, prompt: str, extra: list[str], hook: str | None = None, room=None) -> list[str]:
        args = ["--dangerously-bypass-approvals-and-sandbox", "exec", "--skip-git-repo-check", "--json"]
        if hook:
            args.append("--dangerously-bypass-hook-trust")  # exec runs no untrusted hook otherwise
        return args + extra + [prompt]

    def prepare_hook(self, config: Path, hook: str):
        (config / "hooks.json").write_text(json.dumps({"hooks": {"PostToolUse": [
            {"matcher": "", "hooks": [{"type": "command", "command": hook}]}]}}))

    def resume_args(self, session: str, prompt: str, extra: list[str]) -> list[str] | None:
        return ["exec", "resume", "--dangerously-bypass-approvals-and-sandbox", "--skip-git-repo-check", "--json",
                *extra, session, prompt]

    def session_file(self, home: Path) -> Path | None:
        rollouts = sorted((home / ".codex" / "sessions").rglob("rollout-*.jsonl"))
        return rollouts[-1] if rollouts else None

    def place_session(self, room, session: str, lines: list[str]):
        # Codex finds a session by the id at the end of its rollout's file name
        target = room.config(self) / "sessions" / "2026" / "01" / "01"
        target.mkdir(parents=True, exist_ok=True)
        (target / f"rollout-2026-01-01T00-00-00-{session}.jsonl").write_text("\n".join(lines) + "\n")

    def trail(self, lines: list[str]) -> trails.Trail:
        return trails.codex(lines)

    def usage(self, stdout: str) -> Usage:
        """From the `turn.completed` events: input_tokens includes the cached ones. No cost."""
        u = Usage(cost_usd=None)
        for e in events(stdout):
            if e.get("type") == "turn.completed":
                n = e.get("usage") or {}
                u = u + Usage(n.get("input_tokens", 0), n.get("cached_input_tokens", 0),
                              n.get("cache_write_input_tokens", 0), n.get("output_tokens", 0),
                              n.get("reasoning_output_tokens", 0))
        return _one_run(u)

    def activity(self, event: dict) -> str | None:
        """What one line of the live stream (--json) shows, for the dashboard."""
        if event.get("type") == "turn.completed":
            return "finished"
        item = event.get("item") or {}
        if item.get("type") == "command_execution" and item.get("command"):
            return "runs: " + str(item["command"]).splitlines()[0][:90]
        if item.get("type") == "agent_message" and item.get("text", "").strip():
            return "says: " + item["text"].strip().splitlines()[0][:90]
        if item.get("type") == "file_change":
            return "edits files"
        return None

    def skill_dirs(self, real: Real) -> list[Path]:
        return [real.config / "skills", real.home / ".agents" / "skills"]

    def extra_markers(self, real: Real) -> list[tuple[str, Path]]:
        return [("memories", real.config / "memories" / "memory_summary.md")]

    def custom_agents(self, real: Real) -> tuple[Path, dict[str, str]]:
        """The user's custom agents: a .toml file each, anywhere under agents/. By name, the first
        line of each description. Codex lists them as roles of its spawn_agent tool."""
        folder = real.config / "agents"
        found = {}
        for path in sorted(folder.rglob("*.toml")) if folder.is_dir() else []:
            try:
                data = tomllib.loads(path.read_text())
            except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError):
                continue
            found[data.get("name") or path.stem] = (str(data.get("description") or "").splitlines() or [""])[0]
        return folder, found

    def email(self, real: Real) -> str | None:
        return None

    def billing(self, real: Real) -> str | None:
        data = _json(real.config / self.credentials)
        return None if data is None else "api key" if data.get("OPENAI_API_KEY") else "subscription"


class Pi:
    name = "pi"
    credentials = "auth.json"
    config_dir = ".pi/agent"
    # A fresh agent directory in a room is clean on its own and keeps the project's
    # AGENTS.md; --no-context-files would drop it (experiments/dirty-twin-pi).
    room_flags: list[str] = []
    yolo: list[str] = []  # Pi has no permission prompts
    native_resume = True
    bare_flags = ["--no-extensions"]  # a room run that shows Pi's own tools only
    secret_files = ["auth.json", "models.json"]  # models.json holds the providers' API keys
    snapshot = "tare-snapshot.ts"

    def discover(self) -> Real:
        home = Path.home()
        custom = os.environ.get("PI_CODING_AGENT_DIR")
        return Real(home, Path(custom) if custom else home / ".pi" / "agent", _which("pi"))

    def _settings(self, real: Real) -> dict:
        try:
            return json.loads((real.config / "settings.json").read_text())
        except (OSError, ValueError):
            return {}

    def token_lifetime(self, real: Real) -> float:
        """Lifetime of the default provider's login; API keys do not expire."""
        path = real.config / self.credentials
        try:
            auth = json.loads(path.read_text())
        except (OSError, ValueError):
            raise _lifetime_error(path) from None
        entry = auth.get(self._settings(real).get("defaultProvider", ""), {})
        if entry.get("type") != "oauth":
            return float("inf")
        return entry["expires"] / 1000 - time.time()

    def seed(self, real: Real, config: Path, room):
        # the login, the providers (with their keys) and the default model; nothing else of the setup
        for name in (self.credentials, "models.json"):
            if (real.config / name).exists():
                shutil.copyfile(real.config / name, config / name)
                (config / name).chmod(0o600)
        settings = self._settings(real)
        (config / "settings.json").write_text(json.dumps(
            {k: settings[k] for k in ("defaultProvider", "defaultModel") if k in settings}))

    def room_env(self, room) -> dict[str, str]:
        return {"PI_CODING_AGENT_DIR": room.inside_config(self)}

    def binds(self, real: Real) -> tuple[list[str], str]:
        # the npm package lives in the home directory, which the room does not have: mount it
        package = real.binary.parents[2]  # <package>/dist/bundle/cli.js
        binds = ["--ro-bind", str(package), "/opt/agent/pi"]
        if sys.platform == "darwin":
            # cli.js starts with `env node`, and node lives wherever the user installed it, often under the home
            binds += ["--ro-bind", str(_which("node")), "/opt/agent/node"]
        return binds, "/opt/agent/pi/dist/bundle/cli.js"

    # the probe: Pi has no base-URL variable, so the fake is a provider of its own
    def _provider(self, models: Path, fake_url: str):
        data = json.loads(models.read_text()) if models.exists() else {}
        data.setdefault("providers", {})["tare"] = {"api": "anthropic-messages", "apiKey": "tare", "baseUrl": fake_url,
                                                    "models": [{"id": "fake", "name": "fake"}]}
        models.write_text(json.dumps(data))

    def probe(self, fake_url: str) -> tuple[list[str], dict[str, str]]:
        return ["-p", "--mode", "json", "--no-session", "--provider", "tare", "--model", "fake", PROMPT], {}

    @contextmanager
    def twin(self, real: Real, fake_url: str):
        """The dirty twin runs on a copy of the user's agent directory; the real one is never written."""
        with tempfile.TemporaryDirectory(prefix="tare-pi-twin-") as copy:
            agent_dir = Path(copy) / "agent"
            shutil.copytree(real.config, agent_dir, symlinks=True, ignore=shutil.ignore_patterns("sessions"))
            _absolute_links(real.config, agent_dir)
            self._provider(agent_dir / "models.json", fake_url)
            yield {"PI_CODING_AGENT_DIR": str(agent_dir)}

    def prepare_probe(self, config: Path, fake_url: str):
        self._provider(config / "models.json", fake_url)

    def capture(self, stdout: str, requests: list[dict]) -> Capture | None:
        main = next((r for r in requests if r.get("tools")), None)
        if main is None:
            return None
        text = "\n".join(strings({k: main.get(k) for k in ("system", "messages", "tools")}))
        return Capture(text, {t["name"] for t in main["tools"]}, {})

    def instructions(self, real: Real) -> Path:
        for name in ("AGENTS.override.md", "AGENTS.md", "AGENTS.MD", "CLAUDE.md", "CLAUDE.MD"):
            if (real.config / name).exists():
                return real.config / name
        return real.config / "AGENTS.md"

    def skill_dirs(self, real: Real) -> list[Path]:
        return [real.config / "skills"]

    def extra_markers(self, real: Real) -> list[tuple[str, Path]]:
        return []

    def email(self, real: Real) -> str | None:
        return None

    def billing(self, real: Real) -> str | None:
        auth = _json(real.config / self.credentials) or {}
        entry = auth.get(self._settings(real).get("defaultProvider", ""))
        return None if not entry else "subscription" if entry.get("type") == "oauth" else "api key"

    # unattended runs (Cliff, Swap)
    def run_args(self, prompt: str, extra: list[str], hook: str | None = None, room=None) -> list[str]:
        loaded = ["-e", f"{room.inside_config(self)}/{self.snapshot}"] if hook else []
        return loaded + extra + ["-p", "--mode", "json", prompt]

    def prepare_hook(self, config: Path, hook: str):
        # an extension that hands every top-level tool call to the snapshot hook
        (config / self.snapshot).write_text(f'''import {{ execFileSync }} from "node:child_process";
export default function (pi: any) {{
  pi.on("tool_result", async (event: any) => {{
    if (event.parentToolCallId) return;  // nested calls belong to the call that issued them
    execFileSync("/bin/sh", ["-c", {json.dumps(hook)}], {{ input: JSON.stringify({{ tool_use_id: event.toolCallId }}) }});
  }});
}}
''')

    def resume_args(self, session: str, prompt: str, extra: list[str]) -> list[str] | None:
        return ["--session", session, *extra, "-p", "--mode", "json", prompt]

    def session_file(self, home: Path) -> Path | None:
        sessions = sorted((home / ".pi" / "agent" / "sessions").rglob("*.jsonl"), key=lambda p: p.stat().st_mtime)
        return sessions[-1] if sessions else None

    def place_session(self, room, session: str, lines: list[str]):
        # Pi keeps a working directory's sessions in --<path with dashes>--
        target = room.config(self) / "sessions" / f"--{room.inside_work.strip('/').replace('/', '-')}--"
        target.mkdir(parents=True, exist_ok=True)
        (target / f"2026-01-01T00-00-00-000Z_{session}.jsonl").write_text("\n".join(lines) + "\n")

    def trail(self, lines: list[str]) -> trails.Trail:
        return trails.pi(lines)

    def usage(self, stdout: str) -> Usage:
        """From the assistant messages: input leaves out the cache, and each message names its cost."""
        u = Usage(cost_usd=None)
        for e in events(stdout):
            message = e.get("message") or {}
            if e.get("type") != "message_end" or message.get("role") != "assistant":
                continue
            n = message.get("usage") or {}
            cost = (n.get("cost") or {}).get("total")
            u = u + Usage(n.get("input", 0) + n.get("cacheRead", 0) + n.get("cacheWrite", 0), n.get("cacheRead", 0),
                          n.get("cacheWrite", 0), n.get("output", 0), n.get("reasoning", 0), cost, message.get("model"))
        return _one_run(u)

    def activity(self, event: dict) -> str | None:
        """What one line of the live stream (--mode json) shows, for the dashboard."""
        kind = event.get("type")
        if kind == "agent_end":
            return "finished"
        if kind == "tool_execution_start":
            args = event.get("args") or {}
            detail = args.get("command") or args.get("path") or ""
            return f"{event.get('toolName')}: {str(detail).splitlines()[0][:90] if detail else ''}"
        if kind == "message_end" and (event.get("message") or {}).get("role") == "assistant":
            for block in (event["message"].get("content") or []):
                if block.get("type") == "text" and block.get("text", "").strip():
                    return "says: " + block["text"].strip().splitlines()[0][:90]
        return None


class Antigravity:
    """The Antigravity CLI (`agy`). Its context classes come from experiments/dirty-twin-agy:
    global rules in ~/.gemini/GEMINI.md, global skills in ~/.gemini/config/skills/; files above
    the project, ~/.agents/ and ~/.gemini/skills/ were not read."""

    name = "agy"
    credentials = "antigravity-oauth-token"
    config_dir = ".gemini/antigravity-cli"
    room_flags: list[str] = []
    yolo = ["--dangerously-skip-permissions"]
    # agy keeps a conversation as protobuf; a cut after a step cannot be placed, so Cliff and
    # Swap continue it by handoff
    native_resume = False

    def discover(self) -> Real:
        if sys.platform == "darwin":
            raise TareError("the Antigravity CLI is not supported on macOS yet: its dirty twin needs Linux's overlay "
                            "over ~/.gemini (epic #85)")
        home = Path.home()
        return Real(home, home / ".gemini" / "antigravity-cli", _which("agy"))

    def token_lifetime(self, real: Real) -> float:
        """A Google OAuth refresh does not rotate the refresh token (measured: digests before and
        after a refresh in a room), so a room may refresh its own copy without harm."""
        if not (real.config / self.credentials).exists():
            raise _lifetime_error(real.config / self.credentials)
        return float("inf")

    def seed(self, real: Real, config: Path, room):
        # the login and the chosen model; nothing else of the setup
        shutil.copyfile(real.config / self.credentials, config / self.credentials)
        (config / self.credentials).chmod(0o600)
        try:
            model = json.loads((real.config / "settings.json").read_text()).get("model")
        except (OSError, ValueError):
            model = None
        (config / "settings.json").write_text(json.dumps({"model": model} if model else {}))

    def room_env(self, room) -> dict[str, str]:
        return {}  # agy finds its setup under HOME

    def binds(self, real: Real) -> tuple[list[str], str]:
        return ["--ro-bind", str(real.binary), "/opt/agent/agy"], "/opt/agent/agy"

    # the probe: CLOUD_CODE_URL points agy at the fake, which offers one model
    def probe(self, fake_url: str) -> tuple[list[str], dict[str, str]]:
        return (["-p", PROMPT, "--output-format", "stream-json", "--model", FAKE_MODEL],
                {"CLOUD_CODE_URL": fake_url})

    def prepare_probe(self, config: Path, fake_url: str):
        pass

    @contextmanager
    def twin(self, real: Real, fake_url: str):
        """The dirty twin sees the real setup, but agy writes into ~/.gemini on every run (its
        conversations, caches, onboarding state). So it runs with an overlay over ~/.gemini
        whose writes go to a tmpfs that dies with the run; see twin_argv."""
        mount = tempfile.mkdtemp(prefix="tare-agy-twin-")
        try:
            yield {"TARE_TWIN_MOUNT": mount}
        finally:
            shutil.rmtree(mount, ignore_errors=True)

    def twin_argv(self, argv: list[str], env: dict[str, str], plant: str = "") -> list[str]:
        """Wrap the twin's command: as mapped root in a user and mount namespace, put a tmpfs on
        the mount point and an overlay over ~/.gemini, then run agy as the user's own uid.
        `plant` is shell run inside the overlay first (experiments only)."""
        mount, gemini = env.pop("TARE_TWIN_MOUNT"), Path.home() / ".gemini"
        script = (f'mount -t tmpfs tmpfs "{mount}" && mkdir "{mount}/u" "{mount}/w" && '
                  f'mount -t overlay overlay -o lowerdir="{gemini}",upperdir="{mount}/u",workdir="{mount}/w" "{gemini}" && '
                  f'{plant + " && " if plant else ""}'
                  f'exec unshare --user --map-user={os.getuid()} --map-group={os.getgid()} -- "$@"')
        return ["unshare", "--user", "--map-root-user", "--mount", "/bin/sh", "-c", script, "sh", *argv]

    def capture(self, stdout: str, requests: list[dict]) -> Capture | None:
        main = next((r for r in requests if (r.get("request") or {}).get("tools")), None)
        if main is None:
            return None
        request = main["request"]
        text = "\n".join(strings({k: request.get(k) for k in ("systemInstruction", "contents", "tools")}))
        tools = {d["name"] for t in request["tools"] for d in t.get("functionDeclarations", [])}
        init = next((e.get("init", {}) for e in events(stdout) if e.get("event") == "init"), {})
        return Capture(text, tools, init)

    def instructions(self, real: Real) -> Path:
        return real.home / ".gemini" / "GEMINI.md"  # arrives as <RULE[user_global]>

    def skill_dirs(self, real: Real) -> list[Path]:
        return [real.home / ".gemini" / "config" / "skills"]

    def extra_markers(self, real: Real) -> list[tuple[str, Path]]:
        return []

    def email(self, real: Real) -> str | None:
        return None  # the account's email and name did not reach the prompt

    def billing(self, real: Real) -> str | None:
        data = _json(real.config / self.credentials)
        return None if data is None else "subscription" if data.get("auth_method") == "consumer" else "api key"

    # unattended runs (Cliff, Swap)
    def run_args(self, prompt: str, extra: list[str], hook: str | None = None, room=None) -> list[str]:
        return ["--dangerously-skip-permissions", *extra, "-p", prompt, "--output-format", "stream-json"]

    def prepare_hook(self, config: Path, hook: str):
        """A global PostToolUse hook in the room's ~/.gemini/config. agy hands it the result's
        stepIdx, which becomes the snapshot's id; agy expects {} back."""
        command = f"""sed 's/"stepIdx": *\\([0-9]*\\)/"tool_use_id": "step-\\1"/' | {hook}; echo '{{}}'"""
        (config.parent / "config").mkdir(parents=True, exist_ok=True)
        (config.parent / "config" / "hooks.json").write_text(json.dumps({"tare-snapshot": {"PostToolUse": [
            {"matcher": "", "hooks": [{"type": "command", "command": command, "timeout": 120}]}]}}))

    def resume_args(self, session: str, prompt: str, extra: list[str]) -> list[str] | None:
        return None

    def session_file(self, home: Path) -> Path | None:
        logs = sorted((home / ".gemini" / "antigravity-cli" / "brain").glob("*/.system_generated/logs/transcript_full.jsonl"),
                      key=lambda p: p.stat().st_mtime)
        return logs[-1] if logs else None

    def trail(self, lines: list[str]) -> trails.Trail:
        return trails.agy(lines)

    def usage(self, stdout: str) -> Usage:
        """From the `result` event, as the CLI reports it. No cost, no model."""
        u = Usage(cost_usd=None)
        for e in events(stdout):
            if e.get("event") == "result":
                n = (e.get("result") or {}).get("usage") or {}
                u = u + Usage(n.get("input_tokens", 0), n.get("cache_read_tokens", 0), 0, n.get("output_tokens", 0),
                              n.get("thinking_tokens", 0))
        return _one_run(u)

    def activity(self, event: dict) -> str | None:
        """What one line of the live stream (--output-format stream-json) shows, for the dashboard."""
        if event.get("event") == "result":
            return "finished"
        update = event.get("step_update") or {}
        if update.get("step_type") == "tool" and update.get("state") == "ACTIVE":
            detail = next(iter(((update.get("tool_info") or {}).get("parameters") or {}).values()), "")
            return f"{update.get('tool_name')}: {str(detail).splitlines()[0][:90] if detail else ''}"
        if update.get("step_type") == "agent_response" and (update.get("text_delta") or "").strip():
            return "says: " + update["text_delta"].strip().splitlines()[0][:90]
        return None


AGENTS = {agent.name: agent for agent in (Claude(), Codex(), Pi(), Antigravity())}
