import json
import time
from pathlib import Path

from tare import trail
from tare.agents import Capture, Pi, Real
from tare.room import Room
from tare.probe import score


def jl(*entries):
    return [json.dumps(e) for e in entries]


def test_pi_session_becomes_a_trail_with_steps():
    lines = jl(
        {"type": "session", "version": 3, "id": "s1", "cwd": "/work"},
        {"type": "message", "id": "a", "parentId": None, "message": {"role": "user", "content": "do it"}},
        {"type": "message", "id": "b", "parentId": "a", "message": {"role": "assistant", "content": [
            {"type": "text", "text": "Listing."}, {"type": "toolCall", "id": "c1", "name": "bash", "arguments": {"command": "ls"}}]}},
        {"type": "message", "id": "c", "parentId": "b", "message": {"role": "toolResult", "toolCallId": "c1", "toolName": "bash",
                                                                     "content": [{"type": "text", "text": "README.md"}]}},
    )
    t = trail.pi(lines)
    assert [(e.kind, e.text) for e in t.events] == [("say", "Listing."), ("call", "ls"), ("result", "README.md")]
    assert t.steps[0].ids == ["c1"] and t.steps[0].trail_cut == 3 and t.steps[0].native_cut == 4


def test_pi_activity_names_tool_calls_and_messages():
    pi = Pi()
    assert pi.activity({"type": "tool_execution_start", "toolName": "bash", "args": {"command": "pytest -q"}}) == "bash: pytest -q"
    assert pi.activity({"type": "message_end", "message": {"role": "assistant", "content": [{"type": "text", "text": "Done."}]}}) == "says: Done."
    assert pi.activity({"type": "agent_end"}) == "finished"
    assert pi.activity({"type": "turn_start"}) is None


def real(tmp_path, auth, settings):
    config = tmp_path / "agent"
    config.mkdir()
    (config / "auth.json").write_text(json.dumps(auth))
    (config / "settings.json").write_text(json.dumps(settings))
    (config / "models.json").write_text(json.dumps({"providers": {"x": {"apiKey": "k"}}}))
    return Real(home=tmp_path, config=config, binary=tmp_path / "pi")


def test_pi_login_lifetime_follows_the_default_provider(tmp_path):
    r = real(tmp_path, {"zai": {"type": "api_key", "key": "k"}, "codex": {"type": "oauth", "expires": (time.time() + 600) * 1000}},
             {"defaultProvider": "zai"})
    assert Pi().token_lifetime(r) == float("inf")
    (r.config / "settings.json").write_text(json.dumps({"defaultProvider": "codex"}))
    assert 500 < Pi().token_lifetime(r) < 700


def test_pi_room_keeps_only_login_providers_and_the_default_model(tmp_path):
    r = real(tmp_path, {"zai": {"type": "api_key", "key": "k"}},
             {"defaultProvider": "zai", "defaultModel": "glm", "packages": ["npm:some-extension"], "theme": "dark"})
    room = tmp_path / "room"
    room.mkdir()
    Pi().seed(r, room, Room(tmp_path, tmp_path))
    assert json.loads((room / "settings.json").read_text()) == {"defaultProvider": "zai", "defaultModel": "glm"}
    assert (room / "auth.json").exists() and (room / "models.json").exists()
    assert oct((room / "models.json").stat().st_mode & 0o777) == "0o600"


def test_extension_tools_and_parent_files_are_named(tmp_path):
    parent = tmp_path / "home"
    project = parent / "project"
    project.mkdir(parents=True)
    rule = "Never run anything that saturates the machine without asking."
    (parent / "AGENTS.md").write_text(f"# Rules\n\n{rule}\n")
    r = Real(home=parent, config=parent / ".pi" / "agent", binary=parent / "pi")
    twin = Capture(f"{rule}\nbash read", {"bash", "read", "web_search"}, {})
    bare = Capture("bash read", {"bash", "read"}, {})
    clean = score(Pi(), r, twin, Capture("bash read", {"bash", "read"}, {}), "", "", bare=bare, project=project)
    assert clean.zero and "extensions" in clean.seen and "parent files" in clean.seen
    dirty = score(Pi(), r, twin, Capture(f"{rule}", {"bash", "read", "web_search"}, {}), "", "", bare=bare, project=project)
    found = {(f.kind, f.what) for f in dirty.leaks}
    assert ("extensions", "web_search") in found and ("parent files", "instructions above the project") in found
