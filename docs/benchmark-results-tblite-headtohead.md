# TBLite Head-to-Head Benchmark Results

_Generated 2026-07-03 16:25  — 27/30 cells complete (10 tasks × 3 versions)._

## What was benchmarked

- **Benchmark:** OpenThoughts-TBLite (Terminal-Bench format), run via **Harbor** in per-task Docker containers, graded by **each task's own verifier** (pass = `verifier_result.rewards` > 0). No score is ever fabricated.

- **Task selection:** the **10 hardest** of the 100-task dataset by `lowest_success_rate` (difficulty-ranked); same 10 tasks for every version.

- **Plugin versions (head-to-head):** `0.2.0` (`main`), `0.3.4` (`release/0.3.4`), `0.3.5` (`feat/0.3.5-structure-cleanup` HEAD).

- **Models:** orchestrator = **Claude Opus-4.8 @ effort=max**; implementer = **Codex gpt-5.5 @ reasoning_effort=xhigh, service_tier=default** (verified in codex session logs).

- **Harness:** custom Harbor agent `bench.harbor_agent:CodexOrchestratorAgent` — launches Claude Code in-container, prompts `/codex-orchestrator:orchestrate`, Claude dispatches **real** in-container `codex exec` sessions; both-sides token usage captured (Claude from Harbor, GPT from collected codex session JSONL).

- **Auth:** Claude via `CLAUDE_CODE_OAUTH_TOKEN` (token mode); Codex via `~/.codex/auth.json`.

- **RExBench:** evaluated and **deferred** — GPU-gated (tasks need A100 / 13GB+ VRAM; only `tree-of-thoughts` is API-driven/CPU-feasible) and no executor built. See methodology.


## Results by task

Legend: ✅/❌ = verifier pass/fail · ⚠️ = solved without dispatching Codex (degenerate). `cx` = codex-exec dispatches. Claude/GPT tokens shown as input(/output).


### Pass / fail + Codex dispatches

| # | Task | 0.2.0 pass | 0.3.4 pass | 0.3.5 pass | 0.2.0 cx | 0.3.4 cx | 0.3.5 cx |
|---|------|:--:|:--:|:--:|:--:|:--:|:--:|
| 1 | `book-portfolio-analysis` | ✅ | ✅ | ✅ | 10 | 18 | 8 |
| 2 | `corrupted-filesystem-recovery` | ✅⚠️ | ✅ | ✅ | 0 | 6 | 1 |
| 3 | `breast-cancer-mlflow` | ✅ | ❌ | ✅ | 5 | 1 | 1 |
| 4 | `bloom-filter-cache-penetration-prevention` | ❌ | ❌ | ❌ | 2 | 6 | 1 |
| 5 | `reproducibility-and-envsetup` | ❌ | ❌ | ❌ | 3 | 2 | 2 |
| 6 | `service-deployment-wave-planner` | ✅ | ❌⚠️ | ✅ | 10 | 0 | 1 |
| 7 | `mech-system` | ✅ | ✅ | ✅ | 3 | 6 | 2 |
| 8 | `multi-labeller` | ✅ | ✅ | ❌ | 5 | 5 | 7 |
| 9 | `react-typescript-debugg` | ❌⚠️ | ✅ | ❌ | 0 | 2 | 3 |

### Claude orchestrator cost + tokens (input)

| # | Task | 0.2.0 $ | 0.3.4 $ | 0.3.5 $ | 0.2.0 tok | 0.3.4 tok | 0.3.5 tok |
|---|------|:--:|:--:|:--:|:--:|:--:|:--:|
| 1 | `book-portfolio-analysis` | $4.88 | $4.54 | $3.91 | 3.85M | 3.66M | 3.23M |
| 2 | `corrupted-filesystem-recovery` | $3.65 | $2.90 | $3.55 | 2.10M | 1.68M | 2.75M |
| 3 | `breast-cancer-mlflow` | — | — | — | 2.26M | 874K | 1.31M |
| 4 | `bloom-filter-cache-penetration-prevention` | — | — | — | 2.57M | 2.23M | 2.04M |
| 5 | `reproducibility-and-envsetup` | — | — | — | 592K | 588K | 751K |
| 6 | `service-deployment-wave-planner` | — | $0.76 | $7.41 | 3.52M | 239K | 6.23M |
| 7 | `mech-system` | — | — | — | 2.06M | 2.49M | 2.81M |
| 8 | `multi-labeller` | — | — | — | 1.85M | 1.55M | 3.48M |
| 9 | `react-typescript-debugg` | — | — | $3.48 | 1.04M | 1.22M | 1.18M |

### GPT/Codex implementer tokens (input) + wall time

| # | Task | 0.2.0 gpt | 0.3.4 gpt | 0.3.5 gpt | 0.2.0 wall | 0.3.4 wall | 0.3.5 wall |
|---|------|:--:|:--:|:--:|:--:|:--:|:--:|
| 1 | `book-portfolio-analysis` | 607K | 544K | 289K | 24m | 27m | 21m |
| 2 | `corrupted-filesystem-recovery` | — | 467K | 391K | 15m | 18m | 16m |
| 3 | `breast-cancer-mlflow` | 273K | 38K | 346K | 18m | 16m | 16m |
| 4 | `bloom-filter-cache-penetration-prevention` | 306K | 340K | 321K | 17m | 16m | 16m |
| 5 | `reproducibility-and-envsetup` | 86K | 13K | 23K | 7m | 9m | 9m |
| 6 | `service-deployment-wave-planner` | 2.00M | — | 459K | 33m | 5m | 28m |
| 7 | `mech-system` | 306K | 339K | 272K | 16m | 16m | 16m |
| 8 | `multi-labeller` | 517K | 242K | 281K | 16m | 16m | 16m |
| 9 | `react-typescript-debugg` | 14K | 173K | 62K | 17m | 18m | 16m |

## Summary by version

Stats are over **valid** cells only (Claude actually ran); `⟳` cells hit the session/rate limit and are excluded pending rerun.

| Version | valid | ⟳ limited | passed | pass rate | real-orch | Σ Claude $ | Σ Claude tok | Σ GPT tok | Σ wall |
|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| **0.2.0** | 9 | 0 | 6 | 67% | 7/9 | $8.53 | 20.32M | 4.26M | 2.7h |
| **0.3.4** | 9 | 0 | 5 | 56% | 8/9 | $8.20 | 14.91M | 2.23M | 2.4h |
| **0.3.5** | 9 | 0 | 5 | 56% | 9/9 | $18.36 | 24.22M | 2.54M | 2.6h |

## Methodology & caveats

- **1 run per (task, version)** — no repeats. Claude/Codex orchestration is stochastic (observed codex-dispatch counts varied widely on the same task across versions), so per-task deltas are **directional**, not statistically conclusive. Add `--repeats` for confidence.

- **`codex_sessions`** counts `codex exec` Bash dispatches in the Claude trajectory; **`gpt_sessions`** counts distinct codex session logs with token usage — they differ when a dispatch resumes/reviews an existing session.

- **GPT `cost_usd` is null** — codex session logs carry token counts, not price.

- **Infra fixes made during bring-up** (all in `bench/harbor_agent.py` / `bench/harbor_runner.py`): token-mode auth (reuse-login credentials file is not read in-container); codex+node symlinked into `~/.local/bin` so the agent can actually dispatch codex; `CLAUDE_PLUGIN_ROOT` pinned; per-run unique Harbor output dir; credential hardening (0600/0700, staging removed).


## Reproduce

```bash
# prereqs: docker running; harbor installed; `harbor download openthoughts-tblite`;
#          ~/.codex/auth.json present; CLAUDE_CODE_OAUTH_TOKEN in ./.env (gitignored)
bash .codex-orchestrator/runs/bench-real-infra/run_matrix.sh          # runs the 27 remaining cells
python3 .codex-orchestrator/runs/bench-real-infra/aggregate_results.py # regenerates this doc
```

