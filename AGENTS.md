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
   `scripts/codex_orchestrator/contract.py` and must match `schemas/codex-orchestrator.schema.json` — the
   test `tests/test_schema.py::test_schema_enums_match_runtime_contract` guards this.
4. **Additive & backward-compatible** changes to the CLI/report unless a release explicitly says
   otherwise. Existing commands (`init`, `status`, `add-verification`, `append-event`, `worktree`,
   `report`) must keep working.
5. **Never fake a benchmark number.** Dry-run paths must be deterministic + schema-valid; real paths
   that need missing infra or datasets must **fail loudly** — the external adapters raise a clear
   `RuntimeError` naming the missing dataset/infra env var, and a not-yet-wired runner path raises
   `NotImplementedError` — or exit nonzero, never emitting placeholder results.
6. **Durable state over memory.** Record material facts in the run ledger
   (`.codex-orchestrator/runs/<id>/`), not just in conversation.

## Repo layout

```
.claude-plugin/   plugin.json (v0.3.4), marketplace.json
commands/         thin slash-command triggers that load skills
skills/           orchestrate/, workflow/, report/ playbooks and orchestration references
monitors/         monitors.json
bin/              codex-orch, codex-orch-monitor
templates/        task-prompt.md, review-prompt.md
scripts/          codex_orchestrator/ (the package: cli, gate, ledger, parse, report, contract, …);
                  codex_orch.py + codex_orch_parse.py are thin path-invoked CLI entry points
schemas/          codex-orchestrator.schema.json, codex-task-output.schema.json
bench/            run.py, runners/ (run_replay.py, run_claude.py), compare.py, metrics.py,
                  adapters/ (base, rexbench, tblite, swebench_verified_mini), tiers.json,
                  bench/schemas/benchmark-result.schema.json, cases/ (replay/, local-mini/)
tests/            unittest suite (103 pass, 1 skipped on Python 3.10)
docs/             maintainer docs
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

# Real runs (spend Claude+Codex budget; need infra) are gated: drop --dry-run and
# adapters raise RuntimeError naming missing dataset/infra env vars until wired.

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

## Current status (2026-07-01)

Plugin **v0.3.6**. **Hold merges to `main`** per direction: the 0.3.x stack
(#8, #9, #12, #13, #14, #15, #16) has been collapsed into one held PR,
[#17](https://github.com/alexzh3/codex-orchestrator/pull/17), targeting `main`. #17 is open,
unmerged, and intentionally held.

The test suite is **166 passing tests**. Issues #4, #5, #6, and #11 are closed. Still-open follow-ups are #2/#3/#10 for real
external-benchmark adapters, #7 for the optional Aider Polyglot smoke, #18/#19/#20 for real-infra
follow-ups, and the `scripts/codex_orchestrator/` package split planned for the next cleanup phase.

Built with Claude Opus 4.8 (1M) + Codex CLI 0.131.0.

## Roadmap

### Refactor releases (see `refactor_plan.md`)
**Versioning policy:** stay on the **0.3.x** line — each release bumps the patch (0.3.1, 0.3.2, …),
not the minor. Do not bump to 0.4+ without explicit instruction.
- **0.3.0 Benchmarkability & metadata** — ✅
- **0.3.1 Task protocol** — typed events, file claims + `check-conflicts`, report Task Graph,
  benchmark score wired to the new events. ✅
- **0.3.2 Gate & generated prompts** — `gate` + `doctor`, `render-prompt` + templates + Codex output
  schema, strict report mode, Gate Result rendering. ✅
- **0.3.3 Skills & monitors** — migrate `commands/*` → `skills/<name>/SKILL.md`, `bin/codex-orch`,
  plugin-native monitors. ✅
- **0.3.4 External benchmark adapters** — dry-run and real-mode adapter scaffolding; see benchmark
  roadmap below. ✅
- **0.3.5 Structure cleanup** — Phase A declutter + truth-sync, then Phase B
  `scripts/codex_orchestrator/` package split behind re-export shims. The package split is not done.
- **0.3.6 Consensus evidence basis + blocker hygiene** — ✅ gate-semantics change (documented
  break): resolving consensus can no longer clear failed executable/acceptance verifications
  without a linked passing rerun (same command hash/kind/task, strictly newer) or explicit
  user_override; review blocking_findings block pending-repro; add-verification validates +
  auto-ids; human docs in docs/consensus-and-reviews.md.

### Head-to-head version-quality benchmark (two tiers, select **lowest-success-rate** tasks)
Config in `bench/tiers.json`. Scaffolding done (dry-run + clear RuntimeError on missing real
datasets/infra); real adapters are **infra-gated**:

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
Closed: umbrella tiered suite [#11], local-mini E2E runner [#4], compare dashboard +
false-acceptance [#5], and CI dry-run guards [#6]. Open: real external-benchmark adapters [#2]/[#3]/[#10],
real-infra follow-ups [#18]/[#19]/[#20], optional Aider Polyglot smoke [#7], and the
`scripts/codex_orchestrator/` package split.

### Recommended next steps
1. Complete the remaining structure cleanup: Phase A declutter first, then the
   `scripts/codex_orchestrator/` package split with compatibility shims.
2. Keep held PR #17 green while `main` remains untouched.
3. Build the first **real** adapter — TBLite [#3] — with the real-infra follow-ups #18/#19/#20, then
   run a small gated head-to-head once infrastructure is available.

## How to extend

- **A benchmark adapter:** subclass `bench/adapters/base.py`; keep dry-run deterministic +
  schema-valid (validate against `bench/schemas/benchmark-result.schema.json`); real mode must raise
  a clear `RuntimeError` naming the missing infra / dataset env var until wired. Reuse
  `run_claude.build_claude_argv`.
- **A ledger event type:** add the `$def` to `schemas/codex-orchestrator.schema.json`, mirror enums
  in `scripts/codex_orchestrator/contract.py`, add validation in the `codex_orchestrator` package,
  render it in `scripts/codex_orchestrator/report_render.py`, and extend `tests/test_schema.py` + a
  focused test.
- Always run the full unittest suite + the relevant `bench.run` before proposing changes.
