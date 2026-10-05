from tare.agents import AGENTS


def test_a_resumed_claude_tail_streams_events_like_a_fresh_start():
    claude = AGENTS["claude"]
    fresh = claude.run_args("task", [])
    resumed = claude.resume_args("session", "Continue.", [])
    for flag in ("--output-format", "stream-json", "--verbose"):
        assert flag in fresh and flag in resumed
