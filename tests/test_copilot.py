"""The GitHub Copilot CLI adapter (epic #189, experiments/dirty-twin-copilot)."""
import json
import os
import stat
from pathlib import Path
from types import SimpleNamespace

import pytest

from tare import agents, cli
from tare.agents import AGENTS, Copilot, Real
from tare.probe import score
from tare.room import Room, TareError

STREAMS = Path(__file__).parent / "streams"


@pytest.fixture
def setup(tmp_path, monkeypatch):
    """A Copilot home with a login as config.json lists it, no token variables, no gh."""
    home = tmp_path / "home"
    config = home / ".copilot"
    config.mkdir(parents=True)
    (config / "config.json").write_text("// written by copilot\n" + json.dumps({
        "lastLoggedInUser": {"host": "https://github.com", "login": "octo"},
        "loggedInUsers": [{"host": "https://github.com", "login": "octo", "kind": "githubDotCom"}],
        "installedPlugins": [{"name": "off", "enabled": False, "cache_path": str(config / "installed-plugins/m/off")},
                             {"name": "on", "enabled": True, "cache_path": str(config / "installed-plugins/m/on")}]}))
    for var in Copilot.token_variables:
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setattr(agents.shutil, "which", lambda name: None)
    return Real(home, config, tmp_path / "copilot")


def test_a_copilot_that_is_a_script_is_refused(tmp_path, monkeypatch):
    script = tmp_path / "copilot"
    script.write_text("#!/usr/bin/env node\n")
    monkeypatch.setattr(agents, "_which", lambda name: script)
    with pytest.raises(TareError, match="is a script"):
        Copilot().discover()


def test_the_login_is_taken_in_copilots_order(setup, monkeypatch):
    c = Copilot()
    user = c._user(setup)
    assert user == {"host": "https://github.com", "login": "octo", "kind": "githubDotCom"}
    asked = []
    monkeypatch.setattr(agents, "_security", lambda account, service: asked.append((account, service)) or None)
    with pytest.raises(TareError, match="no token for the Copilot login octo"):
        c.token_lifetime(setup)
    monkeypatch.setattr(agents.sys, "platform", "darwin")
    monkeypatch.setattr(agents, "_security", lambda account, service: asked.append((account, service)) or "kc")
    assert c._token(setup, user) == "kc" and asked[-1] == ("https://github.com:octo", "copilot-cli")

    gh = SimpleNamespace(returncode=0, stdout="from-gh\n")
    monkeypatch.setattr(agents.shutil, "which", lambda name: "/usr/bin/gh")
    calls = []
    monkeypatch.setattr(agents.subprocess, "run", lambda argv, **k: calls.append(argv) or gh)
    assert c._token(setup, user) == "from-gh"
    assert calls[-1] == ["/usr/bin/gh", "auth", "token", "--hostname", "github.com", "--user", "octo"]

    data = json.loads((setup.config / "config.json").read_text().split("\n", 1)[1])
    data["copilotTokens"] = {"https://github.com:octo": "plain"}
    (setup.config / "config.json").write_text(json.dumps(data))
    assert c._token(setup, user) == "plain"

    monkeypatch.setenv("GH_TOKEN", "ghp_classic")  # Copilot refuses classic tokens
    assert c._token(setup, user) == "plain"
    monkeypatch.setenv("GITHUB_TOKEN", "gho_env")
    monkeypatch.setenv("COPILOT_GITHUB_TOKEN", "gho_first")
    assert c._token(setup, user) == "gho_first"
    assert c.token_lifetime(setup) == float("inf")


def test_no_login_in_config_json_is_refused(tmp_path):
    (tmp_path / "config.json").write_text("{}")
    with pytest.raises(TareError, match="no Copilot login"):
        Copilot().token_lifetime(Real(tmp_path, tmp_path, tmp_path / "copilot"))


def test_the_room_gets_the_login_only_and_trusts_the_project(setup, tmp_path, monkeypatch):
    monkeypatch.setenv("COPILOT_GITHUB_TOKEN", "gho_x")
    room = Room(tmp_path / "room-home", tmp_path / "work", inside_work="/work")
    config = room.config(Copilot())
    config.mkdir(parents=True)
    Copilot().seed(setup, config, room)
    data = json.loads((config / "config.json").read_text())
    assert data == {"lastLoggedInUser": {"host": "https://github.com", "login": "octo"},
                    "loggedInUsers": [{"host": "https://github.com", "login": "octo", "kind": "githubDotCom"}],
                    "copilotTokens": {"https://github.com:octo": "gho_x"}, "trustedFolders": ["/work"]}
    assert stat.S_IMODE((config / "config.json").stat().st_mode) == 0o600
    assert sorted(p.name for p in config.iterdir()) == ["config.json"]
    assert Copilot().room_env(room) == {"COPILOT_HOME": "/home/tare/.copilot", "COPILOT_DISABLE_LOGIN_SHELL_ENV": "1"}
    assert "--disable-builtin-mcps" in Copilot().room_flags


def test_the_control_run_works_on_a_copy_and_an_empty_cache(setup):
    (setup.config / "skills" / "mine").mkdir(parents=True)
    (setup.config / "session-state" / "s1").mkdir(parents=True)
    (setup.config / "logs").mkdir()
    with Copilot().twin(setup, "http://fake") as env:
        copy, cache = Path(env["COPILOT_HOME"]), Path(env["COPILOT_CACHE_HOME"])
        assert (copy / "skills" / "mine").is_dir() and (copy / "config.json").exists()
        assert not (copy / "session-state").exists() and not (copy / "logs").exists()
        assert list(cache.iterdir()) == []
        (copy / "written-by-the-run").write_text("x")
    assert not (setup.config / "written-by-the-run").exists() and not copy.exists()


def test_the_probe_points_copilot_at_the_fake_as_anthropic_messages():
    args, env = Copilot().probe("http://127.0.0.1:9")
    assert env == {"COPILOT_PROVIDER_BASE_URL": "http://127.0.0.1:9", "COPILOT_PROVIDER_TYPE": "anthropic",
                   "COPILOT_MODEL": agents.FAKE_MODEL}
    assert args[-2:] == ["--output-format", "json"] and "--no-auto-update" in args


def request(*tools, system="You are Copilot."):
    return {"system": [{"type": "text", "text": system}], "messages": [{"role": "user", "content": "say ok"}],
            "tools": [{"name": t, "description": "", "input_schema": {}} for t in tools]}


def stream(*servers, version="1.0.114"):
    return "\n".join([json.dumps({"type": "session.start", "data": {"copilotVersion": version}}),
                      json.dumps({"type": "session.mcp_servers_loaded", "data": {"servers": [
                          {"name": s, "status": "connected"} for s in servers]}})])


def test_the_capture_names_mcp_tools_as_the_probe_reads_them():
    capture = Copilot().capture(stream("github-mcp-server", "qmd"),
                                [{"tools": []}, request("bash", "github-mcp-server-list_issues", "qmd-query", "qmd2-x")])
    assert capture.tools == {"bash", "mcp__github-mcp-server__list_issues", "mcp__qmd__query", "qmd2-x"}
    assert capture.init == {"version": "1.0.114", "mcp_servers": [{"name": "github-mcp-server", "status": "connected"},
                                                                  {"name": "qmd", "status": "connected"}]}
    assert Copilot().capture("", [{"tools": []}]) is None


def test_the_probe_names_copilots_skills_agents_instructions_and_mcp_by_their_source(setup, tmp_path):
    c = Copilot()
    skill = setup.config / "skills" / "mine"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text("---\nname: mine\ndescription: Mine.\n---\n")
    plugin_skill = setup.config / "installed-plugins" / "m" / "on" / "skills" / "plugged"
    plugin_skill.mkdir(parents=True)
    (setup.config / "installed-plugins" / "m" / "off" / "skills" / "unplugged").mkdir(parents=True)
    (setup.config / "agents").mkdir()
    (setup.config / "agents" / "helper.agent.md").write_text("---\nname: helper\ndescription: Helps a lot.\n---\nBody.\n")
    (setup.config / "copilot-instructions.md").write_text("Always answer like a careful senior engineer would.\n")
    skills = ("<skill>\n  <name>mine</name>\n  <description>Mine.</description>\n  <location>user</location>\n</skill>\n"
              "<skill>\n  <name>plugged</name>\n  <description>P.</description>\n  <location>plugin</location>\n</skill>")
    system = (f"{skills}\nUser-provided custom agents:\n- **helper**: Helps a lot.\n"
              "<custom_instruction>\nAlways answer like a careful senior engineer would.\n</custom_instruction>\n"
              f"cwd {setup.home}/project")
    twin = c.capture(stream("tare-planted"), [request("bash", "tare-planted-query", system=system)])
    room = c.capture(stream("tare-planted"), [request("bash", "tare-planted-query", system=system)])
    clean = c.capture(stream(), [request("bash")])
    leaked = score(c, setup, twin, room, "", "", project=tmp_path / "project")
    assert {f.kind for f in leaked.leaks} == {"instructions", "home path", "mcp", "skills", "agents"}
    assert sorted(f.source for f in leaked.leaks if f.kind == "skills") == sorted(
        [str(setup.config / "skills"), str(plugin_skill.parent)])
    assert next(f for f in leaked.leaks if f.kind == "agents").source == str(setup.config / "agents")
    reading = score(c, setup, twin, clean, "", "", project=tmp_path / "project")
    assert reading.zero and reading.version == "1.0.114"
    assert set(reading.seen) >= {"instructions", "home path", "mcp", "skills", "agents"}


def test_skills_above_the_project_count_up_to_the_repositorys_root(tmp_path):
    (tmp_path / ".agents" / "skills").mkdir(parents=True)
    project = tmp_path / "a" / "b"
    project.mkdir(parents=True)
    assert Copilot().parent_skill_dirs(project) == [tmp_path / ".agents" / "skills"]
    (tmp_path / "a" / ".git").mkdir()
    (tmp_path / "a" / ".github" / "skills").mkdir(parents=True)
    assert Copilot().parent_skill_dirs(project) == [tmp_path / "a" / ".github" / "skills"]
    (project / ".git").mkdir()  # the project is the repository's root: nothing above counts
    assert Copilot().parent_skill_dirs(project) == []


def test_an_unattended_run_reads_its_tokens_from_the_streams_last_checkpoint():
    args = Copilot().run_args("do it", ["--model", "gpt-x"])
    assert args == ["--yolo", "--no-auto-update", "--model", "gpt-x", "-p", "do it", "--output-format", "json"]
    with pytest.raises(TareError, match="Cliff and Swap"):
        Copilot().run_args("do it", [], hook="snapshot")
    u = Copilot().usage((STREAMS / "copilot-skill.jsonl").read_text())
    assert (u.input, u.cached, u.cache_write, u.output, u.model, u.cost_usd, u.runs) == \
        (40633, 27000, 13624, 64, "gpt-6.1-sol", None, 1)
    odd = json.dumps({"type": "session.usage_checkpoint", "data": {"accountingSnapshot": {"tokenDetails": {
        "input": {"tokenCount": "12"}, "output": {"tokenCount": True}, "cache_read": {"tokenCount": -3}}}}})
    u = Copilot().usage(odd + "\n" + '{"type": "result"')  # odd counts, and a last line cut off
    assert (u.input, u.output, u.model) == (0, 0, None)
    assert Copilot().usage("").input == 0


def test_a_recorded_copilot_run_counts_its_skill_and_tools():
    """Copilot CLI 1.0.114 in a macOS room, its default model, asked to "Use the greet skill." in a
    project whose greet skill writes hello.txt."""
    text = (STREAMS / "copilot-skill.jsonl").read_text()
    assert Copilot().uses(text).to_dict() == {"tools": {"apply_patch": 1, "skill": 1}, "skills": {"greet": 1}}
    assert Copilot().activity({"type": "tool.execution_start", "data": {"toolName": "bash",
                                                                         "arguments": {"command": "ls -la\nmore"}}}) == "bash: ls -la"
    assert Copilot().activity({"type": "assistant.message", "data": {"content": "Done.\nok"}}) == "says: Done."
    assert Copilot().activity({"type": "result"}) == "finished"


def test_cliff_and_swap_refuse_copilot(capsys):
    with pytest.raises(SystemExit):
        cli.main(["cliff", "copilot", "task", "--check", "true"])
    assert "copilot does not run in Cliff and Swap yet" in capsys.readouterr().err
    with pytest.raises(SystemExit):
        cli.main(["swap", "task", "--check", "true", "--b", "copilot"])
    assert "copilot does not run in Cliff and Swap yet" in capsys.readouterr().err
    assert "copilot" in AGENTS


def test_the_control_run_copies_what_links_point_to_and_runs_online(setup, tmp_path):
    shared = tmp_path / "shared-skills"
    (shared / "s").mkdir(parents=True)
    (setup.config / "skills").symlink_to(shared)
    with Copilot().twin(setup, "http://fake") as env:
        copy = Path(env["COPILOT_HOME"]) / "skills"
        assert copy.is_dir() and not copy.is_symlink()
        (copy / "written-by-the-run").write_text("x")
        assert env["COPILOT_OFFLINE"] == "false"
    assert not (shared / "written-by-the-run").exists()


def test_a_configured_mcp_server_the_control_run_did_not_connect_makes_the_probe_blind(setup, tmp_path):
    c = Copilot()
    (setup.config / "mcp-config.json").write_text(json.dumps({"mcpServers": {"local-search": {"command": "x"}}}))
    twin = c.capture(stream("github-mcp-server"), [request("bash", "github-mcp-server-list_issues")])
    room = c.capture(stream(), [request("bash")])
    reading = score(c, setup, twin, room, "", "", project=tmp_path / "p")
    assert "mcp" in reading.blind and not reading.zero
    (setup.config / "mcp-config.json").write_text("{}")
    leaked = score(c, setup, twin, twin, "", "", project=tmp_path / "p")
    assert [(f.what, f.source) for f in leaked.leaks if f.kind == "mcp"] == [("github-mcp-server", "connected account (login)")]


def test_a_classic_token_is_refused_from_every_source(setup, monkeypatch):
    c = Copilot()
    user = c._user(setup)
    monkeypatch.setattr(agents.shutil, "which", lambda name: "/usr/bin/gh")
    monkeypatch.setattr(agents.subprocess, "run", lambda argv, **k: SimpleNamespace(returncode=0, stdout="ghp_classic\n"))
    monkeypatch.setattr(agents.sys, "platform", "darwin")
    monkeypatch.setattr(agents, "_security", lambda account, service: "ghp_also_classic")
    assert c._token(setup, user) is None


def test_an_agent_description_written_as_a_yaml_block_is_read(setup):
    (setup.config / "agents").mkdir()
    (setup.config / "agents" / "deep.agent.md").write_text(
        "---\nname: deep\ndescription: >\n  Looks into things.\n  Thoroughly.\ntools: [x]\n---\nBody.\n")
    assert Copilot().custom_agents(setup)[1] == {"deep": "Looks into things."}


def events(*items):
    return "\n".join(json.dumps({"type": kind, "data": data}) for kind, data in items)


def test_mcp_servers_come_from_every_event_and_from_the_configuration_when_the_stream_names_none():
    c = Copilot()
    # the status changes and the tools come before any summary, and the tools before connected
    late = events(("session.mcp_server_status_changed", {"serverName": "local", "status": "pending"}),
                  ("session.mcp_server_tools_loaded", {"serverName": "local", "toolCount": 2}),
                  ("session.mcp_server_status_changed", {"serverName": "local", "status": "connected", "configSource": "user"}),
                  ("session.mcp_server_status_changed", {"serverName": "gone", "status": "connected"}),
                  ("session.mcp_server_removed", {"serverName": "gone"}))
    capture = c.capture(late, [request("bash", "local-query")])
    assert capture.tools == {"bash", "mcp__local__query"}
    assert capture.init["mcp_servers"] == [{"name": "local", "status": "connected", "tools": 2, "source": "user"}]
    # a stream cut off before the servers: the configured names still place the tool
    assert c.capture("", [request("local-query")], known=("local",)).tools == {"mcp__local__query"}
    assert c.capture("", [request("local-query")]).tools == {"local-query"}
    # a name that fits two servers counts for both: the request does not say which offers it
    both = c.capture(stream("team", "team-search"), [request("team-search-query")], known=("other",))
    assert both.tools == {"mcp__team__search-query", "mcp__team-search__query"}


def test_a_server_the_control_run_could_not_use_makes_the_probe_blind_and_a_switched_off_one_does_not(setup, tmp_path):
    c = Copilot()
    room = c.capture(stream(), [request("bash")])
    failed = c.capture(events(("session.mcp_server_status_changed", {"serverName": "github-mcp-server", "status": "failed"})),
                       [request("bash")])
    assert "mcp" in score(c, setup, failed, room, "", "", project=tmp_path / "p").blind
    empty = c.capture(events(("session.mcp_server_status_changed", {"serverName": "prompts", "status": "connected"}),
                             ("session.mcp_server_tools_loaded", {"serverName": "prompts", "toolCount": 0})), [request("bash")])
    assert "mcp" not in score(c, setup, empty, room, "", "", project=tmp_path / "p").blind
    (setup.config / "mcp-config.json").write_text(json.dumps({"mcpServers": {"off": {"command": "x"}, "on": {"command": "y"}}}))
    (setup.config / "settings.json").write_text(json.dumps({"disabledMcpServers": ["off"]}))
    assert c.mcp_configured(setup) == ["on"] and c.mcp_names(setup) == ("off", "on", "github-mcp-server")
    twin = c.capture(stream("on"), [request("on-x")])
    assert "mcp" not in score(c, setup, twin, room, "", "", project=tmp_path / "p").blind


def test_the_rooms_mcp_servers_are_named_by_where_copilot_says_they_come_from(setup, tmp_path):
    c = Copilot()
    twin = c.capture(stream("github-mcp-server"), [request("github-mcp-server-x")])
    room = c.capture(events(("session.mcp_servers_loaded", {"servers": [
        {"name": "github-mcp-server", "status": "connected", "source": "user"},  # the user's own, by that name
        {"name": "bundled", "status": "connected", "source": "builtin"},
        {"name": "projects-own", "status": "connected", "source": "workspace"}]})),
        [request("github-mcp-server-x", "bundled-y", "projects-own-z")])
    leaks = [(f.what, f.source) for f in score(c, setup, twin, room, "", "", project=tmp_path / "p").leaks if f.kind == "mcp"]
    assert leaks == [("bundled", "connected account (login)"), ("github-mcp-server", "MCP server")]


def skill(name, description, location):
    return f"<skill>\n  <name>{name}</name>\n  <description>{description}</description>\n  <location>{location}</location>\n</skill>"


def test_a_skill_the_project_brings_itself_is_not_taken_for_the_users_of_the_same_name(setup, tmp_path):
    c = Copilot()
    (setup.config / "skills" / "browse").mkdir(parents=True)
    project = tmp_path / "project"
    (project / ".agents" / "skills" / "browse").mkdir(parents=True)
    (project / ".git").mkdir()
    ours, users = skill("browse", "Drive a browser.", "project"), skill("browse", "Drive a browser.", "user")
    twin = c.capture(stream(), [request("bash", system=f"{ours}\n{users}")])
    clean = c.capture(stream(), [request("bash", system=ours)])
    reading = score(c, setup, twin, clean, "", "", project=project)
    assert "skills" in reading.seen and not [f for f in reading.leaks if f.kind == "skills"]
    leaked = c.capture(stream(), [request("bash", system=f"{ours}\n{users}")])
    assert [f.source for f in score(c, setup, twin, leaked, "", "", project=project).leaks if f.kind == "skills"] == \
        [str(setup.config / "skills")]


def test_the_control_run_keeps_relative_links_and_nested_names_and_writes_nothing_where_the_user_points(
        setup, tmp_path, monkeypatch):
    shared = setup.home / "shared"
    shared.mkdir()
    (shared / "rules.md").write_text("Be careful.\n")
    (setup.config / "copilot-instructions.md").symlink_to("../shared/rules.md")  # relative to its own folder
    (setup.config / "skills" / "logs").mkdir(parents=True)  # a skill named like a folder left out at the top
    (setup.config / "logs").mkdir()
    (setup.config / "dangling").symlink_to("nowhere")
    (setup.config / "skills" / "loop").symlink_to("..")
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)  # a relative link is not read from the working directory
    monkeypatch.setenv("COPILOT_EVENTS_LOG_DIRECTORY", str(setup.home / "my-events"))
    monkeypatch.delenv("COPILOT_PROCESS_LOG_FILE", raising=False)
    with Copilot().twin(setup, "http://fake") as env:
        copy = Path(env["COPILOT_HOME"])
        assert (copy / "copilot-instructions.md").read_text() == "Be careful.\n"
        assert not (copy / "copilot-instructions.md").is_symlink()
        assert (copy / "skills" / "logs").is_dir() and not (copy / "logs").exists()
        assert not os.path.lexists(copy / "dangling") and not os.path.lexists(copy / "skills" / "loop")
        tmp = copy.parent
        assert env["COPILOT_PKG_CACHE_HOME"] == env["COPILOT_CACHE_HOME"] == str(tmp / "cache")
        assert Path(env["COPILOT_EVENTS_LOG_DIRECTORY"]).parent == tmp and "COPILOT_PROCESS_LOG_FILE" not in env
    assert not (setup.home / "my-events").exists()


def test_the_rooms_login_file_is_private_from_the_moment_it_exists(setup, tmp_path, monkeypatch):
    monkeypatch.setenv("COPILOT_GITHUB_TOKEN", "gho_x")
    room = Room(tmp_path / "room-home", tmp_path / "work", inside_work="/work")
    config = room.config(Copilot())
    config.mkdir(parents=True)
    modes, fdopen = [], os.fdopen
    monkeypatch.setattr(agents.os, "fdopen", lambda fd, *a: modes.append(stat.S_IMODE(os.fstat(fd).st_mode)) or fdopen(fd, *a))
    old = os.umask(0)
    try:
        Copilot().seed(setup, config, room)
    finally:
        os.umask(old)
    assert modes == [0o600] and stat.S_IMODE((config / "config.json").stat().st_mode) == 0o600


def test_yaml_values_lose_their_comments_and_quotes_and_block_headers_their_comments(tmp_path):
    path = tmp_path / "a.agent.md"
    path.write_text("---\nname: plain # a comment\ntitle: \"Quoted # kept\"\n"
                    "description: > # shown in the agent list\n  Looks into things.\n\n  Thoroughly.\n"
                    "note: |2-\n  Kept.\n---\n")
    assert agents._frontmatter(path) == {"name": "plain", "title": "Quoted # kept",
                                         "description": "Looks into things.\n\nThoroughly.", "note": "Kept."}


def test_odd_checkpoint_fields_do_not_stop_the_count():
    odd = json.dumps({"type": "session.usage_checkpoint", "data": {"modelCacheState": 5, "accountingSnapshot": {
        "tokenDetails": {"input": {"tokenCount": 7}}}}})
    u = Copilot().usage(odd)
    assert (u.input, u.model) == (7, None)


def test_instruction_files_of_short_lines_still_give_markers(tmp_path):
    from tare.probe import instruction_lines
    path = tmp_path / "copilot-instructions.md"
    path.write_text("Always answer in French.\nBe brief.\n")
    assert instruction_lines(path) == ["Always answer in French."]
    path.write_text("# Rules\n- be brief\n")
    assert instruction_lines(path) == ["# Rules\n- be brief"]
    path.write_text("ok\n")
    assert instruction_lines(path) == []
    path.write_text("# Instructions\nNever use emojis in answers.\n")  # the heading is no marker
    assert instruction_lines(path) == ["Never use emojis in answers."]


def test_plugins_are_on_unless_switched_off_and_found_where_copilot_installs_them(setup):
    data = json.loads((setup.config / "config.json").read_text().split("\n", 1)[1])
    data["installedPlugins"] += [{"name": "implicit", "marketplace": "mk"},
                                 {"name": "../escape", "marketplace": "mk"}, {"name": "x", "enabled": False, "marketplace": "mk"}]
    (setup.config / "config.json").write_text(json.dumps(data))
    assert Copilot()._enabled_plugins(setup) == [setup.config / "installed-plugins/m/on",
                                                 setup.config / "installed-plugins" / "mk" / "implicit"]


def test_only_a_server_that_can_offer_tools_takes_a_tool_name(setup, tmp_path):
    c = Copilot()
    # the room lists the GitHub server as disabled; a project server's name starts with it
    room = c.capture(events(("session.mcp_servers_loaded", {"servers": [
        {"name": "github-mcp-server", "status": "disabled", "source": "builtin"},
        {"name": "github-mcp-server-docs", "status": "connected", "source": "workspace"}]})),
        [request("github-mcp-server-docs-search")], known=("github-mcp-server",))
    assert room.tools == {"mcp__github-mcp-server-docs__search"}
    twin = c.capture(stream("github-mcp-server"), [request("github-mcp-server-x")])
    assert not [f for f in score(c, setup, twin, room, "", "", project=tmp_path / "p").leaks if f.kind == "mcp"]
    # a failed server does not take a working one's tool, so the control run stays blind for it
    failed = c.capture(events(("session.mcp_servers_loaded", {"servers": [
        {"name": "team", "status": "failed"}, {"name": "team-search", "status": "connected"}]})), [request("team-search-query")])
    assert failed.tools == {"mcp__team-search__query"}
    assert "mcp" in score(c, setup, failed, c.capture(stream(), [request("bash")]), "", "", project=tmp_path / "p").blind
    # a server the stream switched off is not found again by its name in the configuration
    off = c.capture(events(("session.mcp_server_status_changed", {"serverName": "team", "status": "disabled"})),
                    [request("team-search-query", "team-x")], known=("team", "team-search"))
    assert off.tools == {"mcp__team-search__query", "team-x"}


def test_the_projects_own_servers_and_servers_without_tools_ask_nothing_of_the_control_run(setup, tmp_path):
    c = Copilot()
    (setup.config / "mcp-config.json").write_text(json.dumps({"mcpServers": {"prompts": {"command": "x"}}}))
    clean = c.capture(stream(), [request("bash")])
    no_tools = c.capture(events(("session.mcp_server_status_changed", {"serverName": "prompts", "status": "connected"}),
                                ("session.mcp_server_tools_loaded", {"serverName": "prompts", "toolCount": 0})), [request("bash")])
    assert "mcp" not in score(c, setup, no_tools, clean, "", "", project=tmp_path / "p").blind
    (setup.config / "mcp-config.json").write_text("{}")
    project_failed = c.capture(events(("session.mcp_servers_loaded", {"servers": [
        {"name": "proj-db", "status": "failed", "source": "workspace"}]})), [request("bash")])
    assert "mcp" not in score(c, setup, project_failed, clean, "", "", project=tmp_path / "p").blind
    project_only = c.capture(events(("session.mcp_servers_loaded", {"servers": [
        {"name": "proj-db", "status": "connected", "source": "workspace"}]})), [request("proj-db-query")])
    assert "mcp" not in score(c, setup, project_only, clean, "", "", project=tmp_path / "p").seen


def test_the_setup_copy_never_follows_a_link_back_into_itself_or_to_the_root(tmp_path):
    source = tmp_path / "setup"
    (source / "skills").mkdir(parents=True)
    (source / "agents").mkdir()
    (source / "skills" / "s.md").write_text("x")
    (source / "skills" / "a").symlink_to("../agents")  # two links that lead to each other
    (source / "agents" / "b").symlink_to("../skills")
    (source / "root").symlink_to("/")
    agents._copy_setup(source, tmp_path / "copy")
    copy = tmp_path / "copy"
    assert (copy / "skills" / "s.md").exists() and (copy / "skills" / "a").is_dir()
    assert not os.path.lexists(copy / "root") and not os.path.lexists(copy / "skills" / "a" / "b")
    assert not os.path.lexists(copy / "agents" / "b" / "a")


def test_yaml_quotes_keep_their_escapes_and_a_comment_alone_is_no_value(tmp_path):
    path = tmp_path / "a.agent.md"
    path.write_text("---\ndescription: # todo\nsingle: 'Don''t break.'\ndouble: \"Say \\\"hi\\\"\"\n---\n")
    assert agents._frontmatter(path) == {"description": "", "single": "Don't break.", "double": 'Say "hi"'}


def test_a_run_without_counts_stays_unpriced_beside_priced_runs_of_its_side(tmp_path, monkeypatch):
    from tare.usage import Usage, of_run
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    (tmp_path / "tare").mkdir()
    (tmp_path / "tare" / "prices.json").write_text(json.dumps({"source": "test", "date": "2026-11-22",
                                                              "models": {"gpt-x": {"input": 1, "output": 2}}}))
    priced, empty = Usage(1000, 0, 0, 100, 0, None, "gpt-x"), Copilot().usage("")
    events_ = [{"event": "start", "sides": {"a": {"agent": "copilot", "args": []}}},
               {"event": "original", "side": "a", "usage": priced.to_dict()},
               {"event": "original", "side": "a", "usage": empty.to_dict()}]
    side = of_run(events_)["sides"]["a"]["usage"]
    assert side["runs"] == 2 and side["unpriced"] == 1 and abs(side["cost_usd"] - (1000 * 1e-6 + 100 * 2e-6)) < 1e-12
