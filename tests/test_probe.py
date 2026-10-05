import json
from pathlib import Path

import pytest

from tare import probe as probe_module
from tare.agents import Antigravity, Capture, Claude, Codex, Real
from tare.probe import Reading, instruction_lines, render, score


INSTRUCTIONS = "Always answer like a pirate captain, every single time."
EMAIL = "me@example.org"
BUILTIN = {"name": "cc-plugin-telemetry", "path": "builtin"}


@pytest.fixture(autouse=True)
def no_custom_config_dir(monkeypatch):
    monkeypatch.delenv("CLAUDE_CONFIG_DIR", raising=False)



def make_real(tmp_path):
    config = tmp_path / ".claude"
    (config / "skills" / "own-skill").mkdir(parents=True)
    (config / "CLAUDE.md").write_text(f"# Me\n\n{INSTRUCTIONS}\n")
    (tmp_path / ".claude.json").write_text(json.dumps({"oauthAccount": {"emailAddress": EMAIL}}))
    return Real(home=tmp_path, config=config, binary=tmp_path / "claude")


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
    reading = score(Claude(), real, twin_capture(tmp_path), clean_room(), "env HOME\nenv PATH\nenv PWD\n", reach_out)
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
    reading = score(Claude(), real, twin, dirty, reach_in, f"path {tmp_path}/.ssh\n")
    found = {(f.kind, f.what, f.source) for f in reading.leaks}
    assert ("instructions", "global instructions", str(real.config / "CLAUDE.md")) in found
    assert ("home path", f"{tmp_path}/", "your files") in found
    assert ("mcp", "claude_ai_Gmail", "connected account (login)") in found
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
    assert score(Claude(), real, twin, room, "", "").leaks == []


def test_twin_without_the_users_instructions_makes_the_probe_blind(tmp_path):
    real = make_real(tmp_path)
    twin = twin_capture(tmp_path)
    twin.text = twin.text.replace(INSTRUCTIONS, "")
    reading = score(Claude(), real, twin, clean_room(), "", "")
    assert "instructions" in reading.blind
    assert not reading.zero
    assert render(reading, tmp_path).endswith("tare: not proven (blind)")


def test_connected_server_missing_from_the_twin_request_makes_mcp_blind(tmp_path):
    real = make_real(tmp_path)
    twin = twin_capture(tmp_path)
    twin.init["mcp_servers"].append({"name": "plugin:pdf-viewer:pdf", "status": "connected"})
    assert "mcp" in score(Claude(), real, twin, clean_room(), "", "").blind


def test_instruction_lines_skip_short_lines(tmp_path):
    path = tmp_path / "CLAUDE.md"
    path.write_text("# Title\nshort\n" + "x" * 100 + "\n")
    assert instruction_lines(path) == ["x" * 80]
    assert instruction_lines(tmp_path / "missing.md") == []


def test_a_tool_name_mentioned_in_prose_is_not_an_offered_server(tmp_path):
    real = make_real(tmp_path)
    room = clean_room()
    room.text += "\nUse `mcp__qmd__query` for search."
    assert score(Claude(), real, twin_capture(tmp_path), room, "", "").leaks == []


GLOBAL_AGENTS = "Always write the failing test first, then the smallest fix."
MEMORY = "The user works across private research and professional repositories."


def codex_real(tmp_path):
    config = tmp_path / ".codex"
    (config / "skills" / ".system" / "imagegen").mkdir(parents=True)
    (config / "skills" / "clockodo-time-entry").mkdir()
    (tmp_path / ".agents" / "skills" / "dialectic").mkdir(parents=True)
    (config / "memories").mkdir()
    (config / "AGENTS.md").write_text(f"# DNA\n\n{GLOBAL_AGENTS}\n")
    (config / "memories" / "memory_summary.md").write_text(f"v1\n\n{MEMORY}\n")
    return Real(home=tmp_path, config=config, binary=tmp_path / "codex")


def codex_twin(home):
    return Capture("\n".join([GLOBAL_AGENTS, MEMORY, f"<cwd>{home}/project</cwd>", "- imagegen: bundled",
                              "- clockodo-time-entry: book hours", "- dialectic: argue both sides"]),
                   {"shell", "mcp__qmd__query"}, {})


def test_codex_clean_room_reads_zero(tmp_path):
    real = codex_real(tmp_path)
    room = Capture("<cwd>/work</cwd>\n- imagegen: bundled", {"shell"}, {})
    reading = score(Codex(), real, codex_twin(tmp_path), room, "env HOME\nenv CODEX_HOME\n", f"path {tmp_path}/.codex\n")
    assert reading.zero
    assert set(reading.seen) == {"instructions", "memories", "home path", "mcp", "skills", "reach"}
    assert [f.what for f in reading.declared] == ["/home/tare/.codex/auth.json"]


def test_codex_dirty_room_names_instructions_memories_skills_and_mcp(tmp_path):
    real = codex_real(tmp_path)
    twin = codex_twin(tmp_path)
    reading = score(Codex(), real, twin, Capture(twin.text, twin.tools, {}), "", "")
    found = {(f.kind, f.what, f.source) for f in reading.leaks}
    assert ("instructions", "global instructions", str(real.config / "AGENTS.md")) in found
    assert ("memories", "memories", str(real.config / "memories" / "memory_summary.md")) in found
    assert ("skills", "1 skill", str(real.config / "skills")) in found
    assert ("skills", "1 skill", str(tmp_path / ".agents" / "skills")) in found
    assert ("mcp", "qmd", "MCP server") in found
    # the bundled .system skills are the product's, not the user's
    assert not any("imagegen" in f.what for f in reading.leaks)


def test_codex_capture_reads_input_items_and_additional_tools():
    body = {"input": [{"type": "additional_tools", "tools": [{"name": "shell"}, {"name": "mcp__qmd__query"}]},
                      {"type": "message", "role": "user", "content": [{"type": "input_text", "text": "hello"}]}]}
    capture = Codex().capture("", [body])
    assert capture.tools == {"shell", "mcp__qmd__query"}
    assert "hello" in capture.text
    assert Codex().capture("", []) is None


def codex_body(*skill_lines, mcp=True):
    """A first request as Codex 0.159 sends it: tools in namespaces, plugin skills in a developer message."""
    namespaces = [{"type": "namespace", "name": "functions", "tools": [{"type": "function", "name": "exec"}]}]
    if mcp:
        namespaces.append({"type": "namespace", "name": "mcp__cua_repl",
                           "tools": [{"type": "function", "name": "js"}, {"type": "function", "name": "js_reset"}]})
    text = "\n".join(["## Skills", "- imagegen: bundled", *skill_lines])
    return {"input": [{"type": "additional_tools", "tools": namespaces},
                      {"type": "message", "role": "developer", "content": [{"type": "input_text", "text": text}]}]}


PLUGIN_SKILLS = ["- limitless:james: review a plan", "- limitless:learn-anything: teach a topic",
                 "- ponytail:ponytail-help: show the modes"]


def test_codex_capture_names_mcp_namespaces_and_plugin_skills():
    capture = Codex().capture("", [codex_body(*PLUGIN_SKILLS)])
    assert {"mcp__cua_repl__js", "mcp__cua_repl__js_reset", "functions"} <= capture.tools
    assert "functions__exec" not in capture.tools  # only an MCP server's namespace is renamed
    assert capture.init["skills"] == ["limitless:james", "limitless:learn-anything", "ponytail:ponytail-help"]
    assert [p["name"] for p in capture.init["plugins"]] == ["limitless", "ponytail"]
    assert Codex().capture("", [codex_body(mcp=False)]).init == {}


def test_codex_plugin_skills_and_mcp_namespaces_are_seen_and_named_in_a_room(tmp_path):
    real = Real(home=tmp_path, config=tmp_path / ".codex", binary=tmp_path / "codex")
    twin = Codex().capture("", [codex_body(*PLUGIN_SKILLS)])
    clean = score(Codex(), real, twin, Codex().capture("", [codex_body(mcp=False)]), "", "")
    assert clean.zero and {"mcp", "skills", "plugins"} <= set(clean.seen)
    dirty = score(Codex(), real, twin, twin, "", "")
    found = {(f.kind, f.what, f.source) for f in dirty.leaks}
    assert found == {("mcp", "cua_repl", "MCP server"), ("skills", "2 skills", "plugin limitless"),
                     ("skills", "1 skill", "plugin ponytail"), ("plugin", "limitless", "Codex plugin"),
                     ("plugin", "ponytail", "Codex plugin")}


def agy_real(tmp_path):
    gemini = tmp_path / ".gemini"
    (gemini / "config" / "skills" / "own-skill").mkdir(parents=True)
    (gemini / "GEMINI.md").write_text(f"{INSTRUCTIONS}\n")
    return Real(home=tmp_path, config=gemini / "antigravity-cli", binary=tmp_path / "agy")


def test_agy_names_its_global_rule_and_skill_and_reads_zero_when_the_room_has_neither(tmp_path):
    real = agy_real(tmp_path)
    twin = Capture("\n".join([f"<RULE[user_global]>\n{INSTRUCTIONS}\n</RULE[user_global]>",
                              f"- own-skill ({tmp_path}/.gemini/config/skills/own-skill/SKILL.md): the user's skill",
                              f"App Data Directory: {tmp_path}/.gemini/antigravity-cli"]), {"run_command"}, {})
    room = Capture("App Data Directory: /home/tare/.gemini/antigravity-cli", {"run_command"}, {})
    clean = score(Antigravity(), real, twin, room, "env HOME\n", f"path {tmp_path}/.gemini\n")
    assert clean.zero and set(clean.seen) == {"instructions", "home path", "skills", "reach"}
    # the dirty room names the same files under its own home
    dirty = score(Antigravity(), real, twin, Capture(twin.text.replace(str(tmp_path), "/home/tare"), twin.tools, {}), "", "")
    found = {(f.kind, f.source) for f in dirty.leaks}
    assert {("instructions", str(tmp_path / ".gemini" / "GEMINI.md")),
            ("skills", str(tmp_path / ".gemini" / "config" / "skills"))} <= found


def test_agy_capture_reads_the_cloud_code_request():
    body = {"model": "tare-fake", "request": {
        "systemInstruction": {"role": "user", "parts": [{"text": "system words"}]},
        "contents": [{"role": "user", "parts": [{"text": "say ok"}]}],
        "tools": [{"functionDeclarations": [{"name": "run_command", "description": "runs"}]}]}}
    stdout = json.dumps({"event": "init", "init": {"cwd": "/work"}}) + "\n"
    capture = Antigravity().capture(stdout, [{"request": {"contents": []}}, body])
    assert "system words" in capture.text and "say ok" in capture.text
    assert capture.tools == {"run_command"} and capture.init == {"cwd": "/work"}


def test_a_blind_dirty_twin_gets_one_more_try_and_the_reading_says_so(monkeypatch):
    monkeypatch.setattr(probe_module, "TWIN_RETRY_PAUSE", 0)
    twins = iter(["slow", "settled", "never used"])
    readings = {"slow": Reading(blind=["mcp"]), "settled": Reading(seen=["mcp"])}
    reading = probe_module.settle(lambda: next(twins), readings.get)
    assert reading.zero and reading.retried == ["mcp"] and next(twins) == "never used"
    assert "retried   the first dirty twin was blind for mcp" in render(reading, Path("/p"))


def test_a_twin_blind_twice_stays_blind(monkeypatch):
    monkeypatch.setattr(probe_module, "TWIN_RETRY_PAUSE", 0)
    reading = probe_module.settle(lambda: "twin", lambda twin: Reading(blind=["mcp"]))
    assert not reading.zero and reading.blind == ["mcp"]
