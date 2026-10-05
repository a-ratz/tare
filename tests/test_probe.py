import json

from tare.probe import Capture, instruction_lines, render, score
from tare.room import Real

INSTRUCTIONS = "Always answer like a pirate captain, every single time."
EMAIL = "me@example.org"
BUILTIN = {"name": "cc-plugin-telemetry", "path": "builtin"}


def make_real(tmp_path):
    config = tmp_path / ".claude"
    (config / "skills" / "own-skill").mkdir(parents=True)
    (config / "CLAUDE.md").write_text(f"# Me\n\n{INSTRUCTIONS}\n")
    (tmp_path / ".claude.json").write_text(json.dumps({"oauthAccount": {"emailAddress": EMAIL}}))
    return Real(home=tmp_path, config=config, state=tmp_path / ".claude.json", claude=tmp_path / "claude")


def twin_capture(home):
    text = "\n".join([
        INSTRUCTIONS,
        f"memory lives in {home}/.claude/projects/x",
        f"The user's email address is {EMAIL}.",
        "- myplugin:helper: helps with things",
        "- anthropic-skills:docx: makes documents",
        "- own-skill: the user's own skill",
        "- debug: bundled skill",
        "mcp__claude_ai_Gmail__search_threads",
    ])
    init = {"claude_code_version": "9.9", "skills": ["myplugin:helper", "anthropic-skills:docx", "own-skill", "debug"],
            "plugins": [{"name": "myplugin", "path": f"{home}/plugins/myplugin"}, BUILTIN],
            "mcp_servers": [{"name": "qmd", "status": "connected"}, {"name": "claude.ai Gmail", "status": "connected"}]}
    return Capture(text, {"Bash", "mcp__qmd__query"}, init)


def clean_room():
    return Capture(f"The user's email address is {EMAIL}.\n- debug: bundled skill", {"Bash"},
                   {"claude_code_version": "9.9", "skills": ["debug"], "plugins": [BUILTIN], "mcp_servers": []})


def test_clean_room_reads_zero_with_declared_email(tmp_path):
    real = make_real(tmp_path)
    reach_out = f"path {tmp_path}/.claude\nenv HOME\n"
    reading = score(real, twin_capture(tmp_path), clean_room(), "env HOME\nenv PATH\nenv PWD\n", reach_out)
    assert reading.zero
    assert reading.leaks == []
    assert set(reading.seen) == {"instructions", "home path", "mcp", "skills", "plugins", "email", "reach"}
    assert [f.kind for f in reading.declared] == ["email", "credentials"]
    assert render(reading, tmp_path).endswith("tare: 0.00")


def test_dirty_room_names_every_leak_and_its_source(tmp_path):
    real = make_real(tmp_path)
    twin = twin_capture(tmp_path)
    dirty = Capture(twin.text, twin.tools, {**twin.init})
    reach_in = f"path {tmp_path}/.ssh\nenv HOME\nenv SOME_API_KEY\n"
    reading = score(real, twin, dirty, reach_in, f"path {tmp_path}/.ssh\n")
    found = {(f.kind, f.what, f.source) for f in reading.leaks}
    assert ("instructions", "global instructions", str(real.config / "CLAUDE.md")) in found
    assert ("home path", f"{tmp_path}/", "the user's files") in found
    assert ("mcp", "claude_ai_Gmail", "login (claude.ai connector)") in found
    assert ("mcp", "qmd", "MCP server") in found
    assert ("skills", "1 skill", "plugin myplugin") in found
    assert ("skills", "1 skill", "login (account skills)") in found
    assert ("skills", "1 skill", str(real.config / "skills")) in found
    assert ("plugin", "myplugin", f"{tmp_path}/plugins/myplugin") in found
    assert ("reach", f"{tmp_path}/.ssh", "visible inside the room") in found
    assert ("env", "SOME_API_KEY", "inherited environment") in found
    assert not reading.zero
    assert render(reading, tmp_path).endswith(f"tare: {len(reading.leaks)} leaks")


def test_bundled_skill_with_the_users_name_is_not_a_leak(tmp_path):
    real = make_real(tmp_path)
    twin = twin_capture(tmp_path)
    room = clean_room()
    room.text += "\n- own-skill: a bundled skill that happens to share the name"
    assert score(real, twin, room, "", "").leaks == []


def test_twin_without_the_users_instructions_makes_the_probe_blind(tmp_path):
    real = make_real(tmp_path)
    twin = twin_capture(tmp_path)
    twin.text = twin.text.replace(INSTRUCTIONS, "")
    reading = score(real, twin, clean_room(), "", "")
    assert "instructions" in reading.blind
    assert not reading.zero
    assert render(reading, tmp_path).endswith("tare: not proven (blind)")


def test_connected_server_missing_from_the_twin_request_makes_mcp_blind(tmp_path):
    real = make_real(tmp_path)
    twin = twin_capture(tmp_path)
    twin.init["mcp_servers"].append({"name": "plugin:pdf-viewer:pdf", "status": "connected"})
    assert "mcp" in score(real, twin, clean_room(), "", "").blind


def test_instruction_lines_skip_short_lines(tmp_path):
    path = tmp_path / "CLAUDE.md"
    path.write_text("# Title\nshort\n" + "x" * 100 + "\n")
    assert instruction_lines(path) == ["x" * 80]
    assert instruction_lines(tmp_path / "missing.md") == []


def test_a_tool_name_mentioned_in_prose_is_not_an_offered_server(tmp_path):
    real = make_real(tmp_path)
    room = clean_room()
    room.text += "\nUse `mcp__qmd__query` for search."
    assert score(real, twin_capture(tmp_path), room, "", "").leaks == []
