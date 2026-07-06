# Benchmark Results

The public head-to-head result is an OpenThoughts-TBLite benchmark in Terminal-Bench format, run
through Harbor in per-task Docker containers and graded by each task's own verifier. The task set is
the 10 hardest tasks out of 100 by published success rate. Each cell is one run per `(task, config)`,
so the result is directional rather than statistical.

This curated view covers the retained configurations: **0.4.1** (the current `main`), **0.2.0** (kept
as a timed reference), and the two **solo** baselines (a single model, no plugin). The full
seven-version history (0.1.0 → 0.5.0) and all raw artifacts live in the
[`codex-orchestrator-bench`](https://github.com/alexzh3/codex-orchestrator-bench) repo.

Legend: ✅/❌ = verifier pass/fail. ⚠️ = solved without dispatching Codex, a degenerate solo solve.
⏱ = hit the per-task wall-clock timeout (the container is still graded, so ⏱ can accompany a pass).
🔁 = killed by a provider API rate limit (an infra confound, not the plugin).

## As-run (under the harness timeout)

The regime Terminal-Bench actually scores: the agent is killed at the per-task wall-clock budget
(360/900/1800s) and the container is graded as-is.

| # | Task | 0.2.0 | 0.4.1 | solo Claude | solo Codex |
|---|------|:--:|:--:|:--:|:--:|
| 1 | `book-portfolio-analysis` | ✅ | ✅ | ✅ | ✅ |
| 2 | `corrupted-filesystem-recovery` | ✅⚠️ | ✅⚠️ | ✅ | ✅ |
| 3 | `breast-cancer-mlflow` | ✅⏱ | ❌ | ✅ | ❌ |
| 4 | `bloom-filter-cache-penetration-prevention` | ❌⏱ | ❌⏱ | ❌🔁 | ❌ |
| 5 | `reproducibility-and-envsetup` | ❌⏱ | ❌⏱ | ❌ | ✅ |
| 6 | `service-deployment-wave-planner` | ✅⏱ | ✅⏱ | ✅⏱ | ✅ |
| 7 | `mech-system` | ✅⏱ | ✅⏱ | ✅ | ✅ |
| 8 | `multi-labeller` | ✅⏱ | ✅⏱ | ✅ | ✅ |
| 9 | `react-typescript-debugg` | ❌⏱ | ❌⏱ | ✅⏱ | ✅ |
| 10 | `token-auth-websocket` | ✅🔁 | ✅🔁 | ✅🔁 | ✅ |

As-run, the solo baselines lead at **8/10** each, with the orchestrated plugin at **0.2.0 = 7/10**
(including one degenerate solo solve) and **0.4.1 = 6/10**. Orchestration does more per task — scoped
dispatch plus review — so the fixed per-task timeout bites it harder than a solo agent.

## No-timeout (timeout lifted)

The same orchestrated runs re-run with the wall-clock budget lifted, so a solve still in progress at
the budget isn't killed and mis-scored as a fail — this separates latency from capability. The solos
weren't re-run no-timeout (they hit the timeout rarely), so their columns repeat the as-run result as
a reference (ᵃ).

| # | Task | 0.2.0 | 0.4.1 | solo Claude ᵃ | solo Codex ᵃ |
|---|------|:--:|:--:|:--:|:--:|
| 1 | `book-portfolio-analysis` | ✅ | ✅⚠️ | ✅ | ✅ |
| 2 | `corrupted-filesystem-recovery` | ✅⚠️ | ✅⚠️ | ✅ | ✅ |
| 3 | `breast-cancer-mlflow` | ✅ | ✅ | ✅ | ❌ |
| 4 | `bloom-filter-cache-penetration-prevention` | ❌ | ❌ | ❌🔁 | ❌ |
| 5 | `reproducibility-and-envsetup` | ✅ | ✅ | ❌ | ✅ |
| 6 | `service-deployment-wave-planner` | ✅ | ✅ | ✅⏱ | ✅ |
| 7 | `mech-system` | ✅ | ✅ | ✅ | ✅ |
| 8 | `multi-labeller` | ✅ | ✅ | ✅ | ✅ |
| 9 | `react-typescript-debugg` | ✅ | ✅ | ✅⏱ | ✅ |
| 10 | `token-auth-websocket` | ✅🔁 | ✅🔁 | ✅🔁 | ✅ |

Lifting the timeout raises **both 0.2.0 and 0.4.1 to 9/10** — matching or beating the solos' timed
score. So most orchestrated "losses" are the wall-clock timeout killing a solve still in progress,
not a capability gap: 0.2.0 recovers `reproducibility-and-envsetup` and `react-typescript-debugg`;
0.4.1 recovers those plus `breast-cancer-mlflow`. 0.4.1 is the current `main` because it carries the
0.4.0 evidence-basis features at no measured cost; 0.2.0 is retained as the stronger *timed*
reference. `bloom-filter-cache-penetration-prevention` is the one task none of these configurations
solves even un-timed. The compared commits were 0.2.0 (`4a69447`, tag `v0.2.0`) and 0.4.1
(`01a524f`, tag `v0.4.1`).

The orchestrator model was Claude Opus 4.8 with effort=max. The implementer model was Codex gpt-5.5
with reasoning effort xhigh.

Both-sides token usage was captured: Claude usage from Harbor, and GPT/Codex usage from collected
Codex session JSONL logs.

Full raw artifacts, the intermediate versions, aggregation tooling, and run instructions live in the
[`codex-orchestrator-bench`](https://github.com/alexzh3/codex-orchestrator-bench) repo. The
deterministic replay self-test that remains in this repo is part of the unittest suite:

```bash
python3 -m unittest tests.test_long_workflow_report
```
