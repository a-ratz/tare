import json

from tare.agents import AGENTS
from tare.usage import Usage, describe, estimate, price_of, total


def stream(*events):
    return "\n".join(json.dumps(e) for e in events) + "\n"


def test_claude_adds_the_cache_to_the_input_and_takes_its_reported_cost():
    u = AGENTS["claude"].usage(stream(
        {"type": "system", "subtype": "init"},
        {"type": "result", "total_cost_usd": 0.05,
         "usage": {"input_tokens": 18, "cache_creation_input_tokens": 8620, "cache_read_input_tokens": 38767,
                   "output_tokens": 5716},
         "modelUsage": {"claude-haiku-4-5-20251001": {"costUSD": 0.05, "thinkingTokens": 645,
                                                      "canonicalModel": "claude-haiku-4-5"}}}))
    assert (u.input, u.cached, u.cache_write, u.output, u.reasoning) == (47405, 38767, 8620, 5716, 645)
    assert u.cost_usd == 0.05 and u.model == "claude-haiku-4-5" and (u.runs, u.unpriced) == (1, 0)


def test_codex_sums_its_turns_and_reports_no_cost():
    turn = {"type": "turn.completed", "usage": {"input_tokens": 100, "cached_input_tokens": 60, "output_tokens": 9,
                                                "reasoning_output_tokens": 2}}
    u = AGENTS["codex"].usage(stream({"type": "thread.started"}, turn, turn))
    assert (u.input, u.cached, u.output, u.reasoning) == (200, 120, 18, 4)
    assert u.cost_usd is None and (u.runs, u.unpriced) == (1, 1)


def test_pi_adds_the_cache_to_the_input_and_sums_the_cost_of_its_messages():
    message = {"type": "message_end", "message": {"role": "assistant", "model": "glm-5.3", "usage": {
        "input": 2978, "output": 31, "cacheRead": 4480, "cacheWrite": 0, "reasoning": 27, "cost": {"total": 0.005}}}}
    u = AGENTS["pi"].usage(stream(message, {"type": "message_end", "message": {"role": "user"}}, message))
    assert (u.input, u.cached, u.output) == (2 * 7458, 2 * 4480, 62)
    assert abs(u.cost_usd - 0.01) < 1e-9 and u.model == "glm-5.3"


def test_agy_reads_its_result_event():
    u = AGENTS["agy"].usage(stream({"event": "result", "result": {"usage": {
        "input_tokens": 50, "output_tokens": 5, "thinking_tokens": 3, "cache_read_tokens": 20}}}))
    assert (u.input, u.cached, u.output, u.reasoning, u.cost_usd) == (50, 20, 5, 3, None)


def test_an_empty_stream_is_one_run_with_unknown_cost():
    u = AGENTS["claude"].usage("")
    assert (u.input, u.runs, u.unpriced, u.cost_usd) == (0, 1, 1, None)


def test_a_total_keeps_count_of_the_runs_whose_cost_is_unknown():
    s = total([Usage(100, 10, 0, 5, 0, 0.02, "m").to_dict(), Usage(50, 0, 0, 5, 0, None, "m"), None])
    assert (s.input, s.runs, s.unpriced, s.model) == (150, 2, 1, "m") and abs(s.cost_usd - 0.02) < 1e-9
    assert describe(s) == "2 runs, 150 in (10 cached), 10 out, $0.020 for 1 run, cost unknown for 1"
    assert describe(Usage(1_234_567, 0, 0, 2_000, 0, None)) == "1 run, 1.23M in (0 cached), 2.0k out, cost unknown"


def test_prices_come_from_the_users_file_first_then_litellm_with_the_makers_price_first(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    (tmp_path / "tare").mkdir()
    (tmp_path / "tare" / "prices-litellm.json").write_text(json.dumps({"fetched": "2026-10-05", "models": {
        "gpt-x": {"input_cost_per_token": 2e-6, "cache_read_input_token_cost": 1e-7, "output_cost_per_token": 1e-5},
        "aihubmix/glm-9": {"input_cost_per_token": 9e-6, "output_cost_per_token": 9e-6},
        "zai/glm-9": {"input_cost_per_token": 1e-6, "output_cost_per_token": 4e-6}}}))
    assert price_of("gpt-x-high")[0]["input"] == 2e-6  # the effort suffix is dropped
    assert price_of("glm-9")[0]["input"] == 1e-6  # the maker before a reseller
    u = estimate(Usage(1_000_000, 800_000, 0, 10_000, 0, None), "gpt-x")
    assert abs(u.cost_usd - (200_000 * 2e-6 + 800_000 * 1e-7 + 10_000 * 1e-5)) < 1e-9
    assert u.estimated == "LiteLLM prices fetched 2026-10-05" and u.unpriced == 0
    (tmp_path / "tare" / "prices.json").write_text(json.dumps({"source": "my contract", "date": "2026-10-01",
                                                              "models": {"gpt-x": {"input": 1, "output": 2}}}))
    assert price_of("gpt-x") == ({"input": 1e-6, "output": 2e-6}, "prices.json (my contract, 2026-10-01)")
    assert estimate(Usage(10, 0, 0, 1, 0, 0.5), "gpt-x").estimated is None  # a reported cost stays


def test_a_run_reports_estimates_and_marks_subscription_logins(tmp_path, monkeypatch):
    from tare.journal import Journal
    from tare.usage import report
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    (tmp_path / "config" / "tare").mkdir(parents=True)
    (tmp_path / "config" / "tare" / "prices-litellm.json").write_text(json.dumps({"fetched": "2026-10-05", "models": {
        "gpt-x": {"input_cost_per_token": 1e-6, "output_cost_per_token": 1e-5}}}))
    j = Journal(tmp_path)
    j("start", kind="calibrate", sides={"a": {"agent": "codex", "args": ["-m", "gpt-x"], "billing": "subscription"}})
    j("tail", id="a-0", status="running", agent="a")
    j("tail", id="a-0", status="passed", usage={"input": 1000, "output": 100})
    lines = report(tmp_path)
    assert "a codex -m gpt-x: 1 run, 1.0k in (0 cached), 100 out, about $0.002 (estimated from LiteLLM prices" in lines[1]
    assert lines[1].endswith("Subscription login, so the cost is notional")


def test_billing_reads_how_each_login_pays(tmp_path):
    from tare.agents import Real
    claude, codex, agy = tmp_path / "claude", tmp_path / "codex", tmp_path / "agy"
    for d in (claude, codex, agy):
        d.mkdir()
    (claude / ".credentials.json").write_text(json.dumps({"claudeAiOauth": {}}))
    (codex / "auth.json").write_text(json.dumps({"OPENAI_API_KEY": "set"}))
    (agy / "antigravity-oauth-token").write_text(json.dumps({"auth_method": "consumer"}))
    real = lambda config: Real(tmp_path, config, tmp_path / "bin")  # noqa: E731
    assert AGENTS["claude"].billing(real(claude)) == "subscription"
    assert AGENTS["codex"].billing(real(codex)) == "api key"
    assert AGENTS["agy"].billing(real(agy)) == "subscription"
    assert AGENTS["claude"].billing(real(tmp_path / "missing")) is None
