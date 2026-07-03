# Benchmark Results

The public head-to-head result is an OpenThoughts-TBLite benchmark in Terminal-Bench format, run
through Harbor in per-task Docker containers and graded by each task's own verifier. The task set is
the 10 hardest tasks out of 100 by published success rate. Each cell is one run per `(task,
version)`, so the result is directional rather than statistical.

Legend: ✅/❌ = verifier pass/fail. ⚠️ = solved without dispatching Codex, a degenerate solo solve.
`cx` = observed `codex exec` dispatches.

| # | Task | 0.2.0 pass | 0.3.5 pass | 0.2.0 cx | 0.3.5 cx |
|---|------|:--:|:--:|:--:|:--:|
| 1 | `book-portfolio-analysis` | ✅ | ✅ | 10 | 8 |
| 2 | `corrupted-filesystem-recovery` | ✅⚠️ | ✅ | 0 | 1 |
| 3 | `breast-cancer-mlflow` | ✅ | ✅ | 5 | 1 |
| 4 | `bloom-filter-cache-penetration-prevention` | ❌ | ❌ | 2 | 1 |
| 5 | `reproducibility-and-envsetup` | ❌ | ❌ | 3 | 2 |
| 6 | `service-deployment-wave-planner` | ✅ | ✅ | 10 | 1 |
| 7 | `mech-system` | ✅ | ✅ | 3 | 2 |
| 8 | `multi-labeller` | ✅ | ❌ | 5 | 7 |
| 9 | `react-typescript-debugg` | ❌⚠️ | ❌ | 0 | 3 |
| 10 | `token-auth-websocket` | ✅ | ✅ | 2 | 3 |

Raw pass rate was 0.2.0 = 7/10, including one degenerate solo solve, versus 0.3.5 = 6/10.
Real-orchestration fidelity rose from 8/10 to 10/10. On genuinely orchestrated passes, defined as
passed and dispatched Codex, both versions tie at 6/10. The compared versions were 0.2.0
(`4a69447`, tag `v0.2.0`) and 0.3.5 (`2827487`, tag `v0.3.5`).

The orchestrator model was Claude Opus 4.8 with effort=max. The implementer model was Codex
gpt-5.5 with reasoning effort xhigh.

Both-sides token usage was captured: Claude usage from Harbor, and GPT/Codex usage from collected
Codex session JSONL logs.

Full raw artifacts, the omitted 0.3.4 column, aggregation tooling, and run instructions live in the
[`codex-orchestrator-bench`](https://github.com/alexzh3/codex-orchestrator-bench) repo. The
deterministic replay self-test that remains in this repo is:

```bash
python3 -m bench.run --suite replay
```
