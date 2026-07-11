# Benchmark Results

> **Historical results:** This document preserves measurements from the schema-driven v0.2.0 and
> v0.4.1 plugin. The prompt-first runtime does not include a benchmark command or adapter.

Benchmark tooling, intermediate versions, and raw run data are kept in the currently private
[`codex-orchestrator-bench`](https://github.com/alexzh3/codex-orchestrator-bench) repository.

The public head-to-head result is an OpenThoughts-TBLite benchmark in Terminal-Bench format, run
through Harbor in per-task Docker containers and graded by each task's own verifier. The task set is
the 10 hardest tasks out of 100 by published success rate. Each cell is one run per `(task, config)`,
so the result is directional rather than statistical.

This curated view covers the retained configurations: **0.4.1** (the then-current release), **0.2.0**
(kept as a timed reference), and the two **solo** baselines (a single model, no plugin). These are
historical benchmark-series labels; prompt-first v0.5.0 has no configuration or results in this
series.

Legend: ✅/❌ = verifier pass/fail. ⚠️ = solved without assigning work to Codex, a degenerate solo solve.
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
Codex execution plus review — so the fixed per-task timeout bites it harder than a solo agent.

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
0.4.1 recovers those plus `breast-cancer-mlflow`. 0.4.1 was retained for this comparison because it carries the
0.4.0 evidence-basis features at no measured cost; 0.2.0 is retained as the stronger *timed*
reference. `bloom-filter-cache-penetration-prevention` is the one task none of these configurations
solves even un-timed. The compared commits were 0.2.0 (`4a69447`, tag `v0.2.0`) and 0.4.1
(`01a524f`, tag `v0.4.1`).

The orchestrator model was Claude Opus 4.8 with effort=max. The implementer model was Codex gpt-5.5
with reasoning effort xhigh.

## Token usage (as-run)

Both-sides token usage was captured: Claude usage from Harbor, and GPT/Codex usage from collected
Codex-agent JSONL logs. Numbers are for the as-run (timed) regime — one run per `(task, config)`.

Totals per configuration:

| Configuration | Σ tokens (as-run) | Claude Σ | Codex Σ | Codex sess |
|---|--:|--:|--:|--:|
| 0.2.0 (orchestrated) | 29.99M | 24.98M | 5.01M | 23 |
| 0.4.1 (orchestrated) | 31.77M | 27.71M | 4.06M | 19 |
| solo Claude (Opus 4.8 max) | 14.49M | 14.49M | — | — |
| solo Codex (gpt-5.5 xhigh) | 5.44M | — | 5.44M | 20 |

Orchestrated runs split tokens across the **Claude** orchestrator and the **Codex** implementer; a
solo run uses one model. The orchestrated configs spend ~2–6× the tokens of the solo baselines —
scoped Codex execution plus the review/consensus loop is the cost of the higher no-timeout pass rate.

Combined Claude+Codex tokens per task (solo = single model):

| # | Task | 0.2.0 | 0.4.1 | solo Claude | solo Codex |
|---|------|:--:|:--:|:--:|:--:|
| 1 | `book-portfolio-analysis` | 4.56M | 5.14M | 1.26M | 458K |
| 2 | `corrupted-filesystem-recovery` | 2.16M | 580K | 846K | 170K |
| 3 | `breast-cancer-mlflow` | 2.60M | 3.17M | 1.18M | 851K |
| 4 | `bloom-filter-cache-penetration-prevention` | 2.94M | 3.35M | 1.26M | 556K |
| 5 | `reproducibility-and-envsetup` | 703K | 788K | 270K | 160K |
| 6 | `service-deployment-wave-planner` | 5.64M | 6.64M | 5.29M | 454K |
| 7 | `mech-system` | 2.43M | 2.51M | 604K | 318K |
| 8 | `multi-labeller` | 2.43M | 2.87M | 402K | 231K |
| 9 | `react-typescript-debugg` | 1.11M | 1.84M | 1.93M | 1.44M |
| 10 | `token-auth-websocket` | 5.41M | 4.88M | 1.44M | 798K |
