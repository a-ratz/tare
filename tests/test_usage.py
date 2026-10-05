import json

from tare.agents import AGENTS
from tare.usage import Usage, describe, total


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
