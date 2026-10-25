# Tokens and cost

[← Documentation](README.md) · [Measuring agents in rooms](measuring.md)

Every Calibrate, Swap and Cliff report ends with the tokens and the cost of each side, of the
check (a judge agent costs tokens too) and of the whole run:

```text
  usage     a claude --model haiku: 1 run, 42.3k in (34.8k cached), 352 out, $0.020. Subscription login, so the cost is notional
            b codex -m gpt-6.1-sol: 1 run, 42.1k in (38.5k cached), 129 out, about $0.012 (estimated from LiteLLM prices fetched 2026-10-05). Subscription login, so the cost is notional
            check (the judge): 2 runs, 102.0k in (92.7k cached), 471 out, $0.061
            total: 4 runs, 186.4k in (166.0k cached), 952 out, about $0.093 (estimated from LiteLLM prices fetched 2026-10-05)
```

## Where the prices come from

Claude Code and Pi report their cost themselves. Codex and the Antigravity CLI report only
tokens, so tare estimates their cost from a price table, and only when it knows the model: pass
it with `-m` or `--model`.

- `tare prices update` fetches LiteLLM's public price table.
- `~/.config/tare/prices.json` overrides single models with your own prices (in dollars per
  million tokens, with a source and a date).

With a subscription login the cost is what the same tokens would cost through the API, so the
report calls it notional. The [dashboard](dashboard.md) shows the same totals while the run goes
on, and the run directory keeps them in `usage.json`.
