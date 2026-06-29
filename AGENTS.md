# AGENTS.md

Guidance for AI agents (Codex, Claude Code, etc.) working in this repository, plus the live status
and roadmap for the in-progress refactor + benchmark effort.

This repo **is** the `codex-orchestrator` Claude Code plugin: Claude plans / monitors / reviews /
gates, and **Codex implements**. When you work here, follow that division.

## Golden rules

1. **Codex implements, Claude orchestrates.** Substantive code/schema/test/doc changes are done by
   scoped Codex sessions with a bounded prompt, explicit file ownership, and a verification gate.
   Claude reviews the real diff, runs an independent `codex exec review`, and records evidence.
2. **Stdlib only.** No third-party Python deps. Config is JSON (not YAML).
3. **Keep the schema contract in sync.** Ledger event enums live in
   `scripts/codex_orch_contract.py` and must match `schemas/codex-orchestrator.schema.json` — the
   test `tests/test_schema.py::test_schema_enums_match_runtime_contract` guards this.
4. **Additive & backward-compatible** changes to the CLI/report unless a release explicitly says
   otherwise. Existing commands (`init`, `status`, `add-verification`, `append-event`, `worktree`,
   `report`) must keep working.
5. **Never fake a benchmark number.** Dry-run paths must be deterministic + schema-valid; real
   paths that need missing infra must **fail loudly** (`NotImplementedError` / nonzero exit), never
   emit placeholder results.
6. **Durable state over memory.** Record material facts in the run ledger
   (`.codex-orchestrator/runs/<id>/`), not just in conversation.

## Repo layout

```
.claude-plugin/   plugin.json (v0.3.0), marketplace.json
commands/         slash commands: orchestrate.md, workflow.md, report.md
scripts/          codex_orch.py (ledger CLI), codex_orch_parse.py (JSONL session parser),
                  codex_orch_contract.py (enums), codex_orch_report.py (report compiler)
schemas/          codex-orchestrator.schema.json, benchmark-result.schema.json
bench/            run.py, runners/ (run_replay.py, run_claude.py), compare.py, metrics.py,
                  adapters/ (base, rexbench, tblite, swebench_verified_mini), tiers.json,
                  cases/ (replay/, local-mini/)
tests/            unittest suite (46 tests)
references/       monitoring.md (Codex JSONL monitoring recipes)
```

## Common commands

```bash
# Tests (must stay green; add coverage with changes)
python3 -m unittest discover -s tests -v

# Deterministic protocol benchmark (no models/API — CI-friendly)
python3 -m bench.run --suite replay

# Head-to-head harness (dry-run mock = zero API cost)
python3 -m bench.run --suite local-mini --plugin-ref <ref> --dry-run
python3 -m bench.run --tier tiny   --plugin-ref <ref> --dry-run    # 3 RExBench + 10 TBLite = 13
python3 -m bench.run --tier normal --plugin-ref <ref> --dry-run    # 6 + 15 + 7 = 28
python3 -m bench.compare --baseline a.jsonl --candidate b.jsonl

# Real runs (spend Claude+Codex budget; need infra) are gated: drop --dry-run and the
# adapters raise NotImplementedError until their dataset/grader is wired.

# Ledger CLI (orchestration bookkeeping)
python3 scripts/codex_orch.py ensure-run --repo . --run-id <id> --plugin-ref <ref>
python3 scripts/codex_orch.py report --repo . --run-id <id>
python3 scripts/codex_orch.py benchmark --repo . --run-id <id> --suite <s> --case-id <c>
```

## Orchestration model

Durable run ledger lives under `.codex-orchestrator/runs/<run-id>/`:
`state.json` (compact state) · `ledger.jsonl` (append-only events) · `report.md` (authored Summary/
Changes + generated evidence) · `prompts/` · `logs/` (captured Codex JSONL) · `artifacts/`.

Dispatch pattern for a Codex session: write a bounded prompt to `prompts/<stem>.md`; launch
`codex exec --json -s workspace-write -c approval_policy=never --output-schema <strict-schema>
-o logs/<stem>-final.json - < prompt > logs/<stem>.jsonl`; monitor with
`scripts/codex_orch_parse.py state/tail`; review the diff; run `codex exec review --base <branch>`;
record `verification` + `consensus`; gate; commit. Resume the same session for same-task fix loops
(`codex exec resume <thread-id>`). Note: strict `--output-schema` requires
`additionalProperties:false` + all-required; `codex exec review --base` cannot take a custom prompt.

## Current status (2026-06-29)

Plugin **v0.3.2** (in progress). **Hold merges to `main`** per direction — each release is consolidated
onto its own `release/0.3.x` branch (approve PRs in the UI: GitHub blocks author self-approval). `main`
stays untouched. ~65 tests green. Open PR stack (each branches off the previous):

| PR | Branch | Release | Tests |
|----|--------|---------|-------|
| [#8](https://github.com/alexzh3/codex-orchestrator/pull/8)   | `feat/0.3-benchmarkability` | 0.3.0 benchmarkability & metadata | 33 |
| [#9](https://github.com/alexzh3/codex-orchestrator/pull/9)   | `feat/bench-local-mini-e2e` | local-mini E2E head-to-head harness | 40 |
| [#12](https://github.com/alexzh3/codex-orchestrator/pull/12) | `feat/bench-tiers`          | tier-aware benchmark suite | 46 |
| [#13](https://github.com/alexzh3/codex-orchestrator/pull/13) | `docs/agents-and-roadmap`   | this file | 46 |
| [#14](https://github.com/alexzh3/codex-orchestrator/pull/14) | `feat/0.3.1-task-protocol`  | 0.3.1 task protocol & enriched ledger | 55 |
| _next_ | `feat/0.3.2-gate-prompts` | 0.3.2 gate, doctor, render-prompt, strict report | 63+ |

Consolidated: **`release/0.3.1`** = #8→#14 merged off `main`. Every PR's independent `codex exec review`
found real bugs, all fixed via consensus loops. Built with Claude Opus 4.8 + Codex CLI 0.131.0 +
Claude Code 2.1.195. Once 0.3.2–0.3.4 land they get `release/0.3.2`–`release/0.3.4` branches, then a
cross-version daily benchmark compares `main` vs each.

## Roadmap

### Refactor releases (see `refactor_plan.md`)
**Versioning policy:** stay on the **0.3.x** line — each release bumps the patch (0.3.1, 0.3.2, …),
not the minor. Do not bump to 0.4+ without explicit instruction.
- **0.3.0 Benchmarkability & metadata** — ✅ (on `release/0.3.1`, PR #8)
- **0.3.1 Task protocol** — typed events, file claims + `check-conflicts`, report Task Graph,
  benchmark score wired to the new events. ✅ (on `release/0.3.1`, PR #14)
- **0.3.2 Gate & generated prompts** — `gate` + `doctor`, `render-prompt` + templates + Codex output
  schema, strict report mode, Gate Result rendering. *(in progress, PR #15)*
- **0.3.3 Skills & monitors** — migrate `commands/*` → `skills/<name>/SKILL.md`, `bin/codex-orch`,
  plugin-native monitors, finish `scripts/codex_orchestrator/` package split (highest conflict → last).
- **0.3.4 External benchmark adapters** — see benchmark roadmap below.

### Head-to-head version-quality benchmark (two tiers, select **lowest-success-rate** tasks)
Config in `bench/tiers.json`. Scaffolding done (dry-run); real adapters are **infra-gated**:

| Benchmark | Tier use | Adapter (real) | Infra | Issue |
|-----------|----------|----------------|-------|-------|
| **TBLite** (OpenThoughts-TBLite, 100 Terminal-Bench tasks) | tiny 10 / normal 15 | Harbor `--agent-import-path` wrapping `claude -p --plugin-dir` | Harbor sandbox | [#3](https://github.com/alexzh3/codex-orchestrator/issues/3) |
| **RExBench** (12 research-eng tasks, arXiv 2506.22598) | tiny 3 / normal 6 | RExBench executor | repo + grader | [#10](https://github.com/alexzh3/codex-orchestrator/issues/10) |
| **SWE-bench Verified Mini** (50, HAL; hard 1hr+ band) | normal 7 | official Docker evaluator | Docker ~5GB | [#2](https://github.com/alexzh3/codex-orchestrator/issues/2) |

Each real run measures **external pass/fail** (the benchmark's own grader) **+ orchestration sidecar
metrics** (report_score, gate false-acceptance, file-conflict count, prompt/log coverage) from the
produced `.codex-orchestrator/` run dir, aggregated by `bench.compare`. External score is
model-dominated; the **sidecar** is where harness/plugin versions actually separate.

### Open issues
Umbrella tiered suite [#11]; adapters [#2]/[#3]/[#10]; local-mini E2E runner [#4]; compare dashboard +
false-acceptance [#5]; CI dry-run guards (replay + tiers + unittest on every PR) [#6]; Aider Polyglot
smoke (optional) [#7].

### Recommended next steps
1. Merge the stack **#8 → #9 → #12** to land the foundation on `main`.
2. Wire CI [#6] (no API cost) so the dry-run replay/tier suites + unittest guard every PR.
3. Then build the first **real** adapter — TBLite [#3] (daily-loop cornerstone) — and run a small
   gated head-to-head (`main` vs `0.3`) for the first real version-quality number.

## How to extend

- **A benchmark adapter:** subclass `bench/adapters/base.py`; keep dry-run deterministic +
  schema-valid (validate against `schemas/benchmark-result.schema.json`); real mode must raise
  `NotImplementedError` naming the infra until wired. Reuse `run_claude.build_claude_argv`.
- **A ledger event type:** add the `$def` to `schemas/codex-orchestrator.schema.json`, mirror enums
  in `scripts/codex_orch_contract.py`, add validation in `scripts/codex_orch.py`, render it in
  `scripts/codex_orch_report.py`, and extend `tests/test_schema.py` + a focused test.
- Always run the full unittest suite + the relevant `bench.run` before proposing changes.
