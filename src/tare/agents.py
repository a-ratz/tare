"""What tare has to know about each agent CLI (CONCEPT.md, "Adapters").

An adapter says where the user's real setup lives, how its login is copied into a room,
how the CLI is pointed at the fake endpoint, how the captured request is read, and which
of the user's files mark their context.
"""
import base64
import json
import os
import shutil
import time
from dataclasses import dataclass
from pathlib import Path

from . import trail as trails
from .room import ROOM_HOME, ROOM_PROJECT, TareError

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
    init: dict  # the CLI's own report of what it loaded, where it gives one


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


def _lifetime_error(path: Path) -> TareError:
    return TareError(f"no login at {path}: log in with the agent first")


class Claude:
    name = "claude"
    credentials = ".credentials.json"
    room_config = f"{ROOM_HOME}/.claude-config"
    # Login-carried connectors and account skills arrive unless these are passed (CONCEPT.md, layer 1).
    room_flags = ["--strict-mcp-config", "--setting-sources", "project,local"]
    yolo = ["--dangerously-skip-permissions"]
    native_resume = True  # Cliff resumes its own session; Swap prices handoffs against it

    def discover(self) -> Real:
        home = Path.home()
        custom = os.environ.get("CLAUDE_CONFIG_DIR")
        return Real(home, Path(custom) if custom else home / ".claude", _which("claude"))

    def state(self, real: Real) -> Path:
        # .claude.json moves with CLAUDE_CONFIG_DIR, otherwise it sits in the home directory
        return real.config / ".claude.json" if os.environ.get("CLAUDE_CONFIG_DIR") else real.home / ".claude.json"

    def token_lifetime(self, real: Real) -> float:
        path = real.config / self.credentials
        try:
            return json.loads(path.read_text())["claudeAiOauth"]["expiresAt"] / 1000 - time.time()
        except (OSError, ValueError, KeyError, TypeError):
            raise _lifetime_error(path) from None

    def seed(self, real: Real, config: Path):
        shutil.copyfile(real.config / self.credentials, config / self.credentials)
        (config / self.credentials).chmod(0o600)
        (config / ".claude.json").write_text(json.dumps(
            {"hasCompletedOnboarding": True, "projects": {ROOM_PROJECT: {"hasTrustDialogAccepted": True}}}))

    def room_env(self) -> dict[str, str]:
        # A custom base URL turns tool search off; keep probe and run in the same form.
        return {"CLAUDE_CONFIG_DIR": self.room_config, "ENABLE_TOOL_SEARCH": "true"}

    def binds(self, real: Real) -> tuple[list[str], str]:
        """bwrap arguments that make the CLI available, and the command inside the room."""
        return ["--ro-bind", str(real.binary), "/opt/agent/claude"], "/opt/agent/claude"

    def probe(self, fake_url: str) -> tuple[list[str], dict[str, str]]:
        """Arguments for one probe turn, and the environment that points the CLI at the fake."""
        args = ["-p", "--output-format", "stream-json", "--verbose", "--no-session-persistence", PROMPT]
        return args, {"ANTHROPIC_BASE_URL": fake_url, "ENABLE_TOOL_SEARCH": "true"}

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
    def run_args(self, prompt: str, extra: list[str], hook: str | None = None) -> list[str]:
        args = ["--dangerously-skip-permissions"]
        if hook:
            args += ["--settings", json.dumps({"hooks": {"PostToolUse": [
                {"matcher": "", "hooks": [{"type": "command", "command": hook}]}]}})]
        return args + extra + ["-p", prompt, "--output-format", "stream-json", "--verbose"]

    def prepare_hook(self, config: Path, hook: str):
        pass  # passed with --settings in run_args

    def resume_args(self, session: str, prompt: str, extra: list[str]) -> list[str] | None:
        return ["--dangerously-skip-permissions", *extra, "-p", "--resume", session, prompt]

    def session_file(self, home: Path) -> Path | None:
        sessions = sorted((home / ".claude-config" / "projects").rglob("*.jsonl"), key=lambda p: p.stat().st_size)
        return sessions[-1] if sessions else None

    def place_session(self, home: Path, session: str, lines: list[str]):
        target = home / ".claude-config" / "projects" / "-work"
        target.mkdir(parents=True, exist_ok=True)
        (target / f"{session}.jsonl").write_text("\n".join(lines) + "\n")

    def trail(self, lines: list[str]) -> trails.Trail:
        return trails.claude(lines)

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


class Codex:
    name = "codex"
    credentials = "auth.json"
    room_config = f"{ROOM_HOME}/.codex"
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

    def seed(self, real: Real, config: Path):
        shutil.copyfile(real.config / self.credentials, config / self.credentials)
        (config / self.credentials).chmod(0o600)
        (config / "config.toml").write_text(f'[projects."{ROOM_PROJECT}"]\ntrust_level = "trusted"\n')

    def room_env(self) -> dict[str, str]:
        return {"CODEX_HOME": self.room_config}

    def binds(self, real: Real) -> tuple[list[str], str]:
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

    def capture(self, stdout: str, requests: list[dict]) -> Capture | None:
        main = next((r for r in requests if "input" in r), None)
        if main is None:
            return None
        tools = {t.get("name") for t in main.get("tools", []) if t.get("name")}
        for item in main.get("input", []):
            tools |= {t.get("name") for t in item.get("tools", []) or [] if isinstance(t, dict) and t.get("name")}
        text = "\n".join(strings({k: main.get(k) for k in ("instructions", "input", "tools")}))
        return Capture(text, tools, {})

    def instructions(self, real: Real) -> Path:
        return real.config / "AGENTS.md"

    def run_args(self, prompt: str, extra: list[str], hook: str | None = None) -> list[str]:
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

    def place_session(self, home: Path, session: str, lines: list[str]):
        # Codex finds a session by the id at the end of its rollout's file name
        target = home / ".codex" / "sessions" / "2026" / "01" / "01"
        target.mkdir(parents=True, exist_ok=True)
        (target / f"rollout-2026-01-01T00-00-00-{session}.jsonl").write_text("\n".join(lines) + "\n")

    def trail(self, lines: list[str]) -> trails.Trail:
        return trails.codex(lines)

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

    def email(self, real: Real) -> str | None:
        return None


class Pi:
    name = "pi"
    credentials = "auth.json"
    room_config = f"{ROOM_HOME}/.pi/agent"
    room_flags: list[str] = []  # decided by the dirty twin, experiments/dirty-twin-pi
    yolo: list[str] = []  # Pi has no permission prompts
    native_resume = False

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

    def seed(self, real: Real, config: Path):
        # the login, the providers (with their keys) and the default model; nothing else of the setup
        for name in (self.credentials, "models.json"):
            if (real.config / name).exists():
                shutil.copyfile(real.config / name, config / name)
                (config / name).chmod(0o600)
        settings = self._settings(real)
        (config / "settings.json").write_text(json.dumps(
            {k: settings[k] for k in ("defaultProvider", "defaultModel") if k in settings}))

    def room_env(self) -> dict[str, str]:
        return {"PI_CODING_AGENT_DIR": self.room_config}

    def binds(self, real: Real) -> tuple[list[str], str]:
        # the npm package lives in the home directory, which the room does not have: mount it
        package = real.binary.parents[2]  # <package>/dist/bundle/cli.js
        return ["--ro-bind", str(package), "/opt/agent/pi"], "/opt/agent/pi/dist/bundle/cli.js"


AGENTS = {agent.name: agent for agent in (Claude(), Codex(), Pi())}
