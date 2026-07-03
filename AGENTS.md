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
5. **Never fake a benchmark number.** Benchmark or evaluation results must come from real artifacts;
   if required infra or data is unavailable, fail loudly or document the absence rather than
   emitting placeholder results.
6. **Durable state over memory.** Record material facts in the run ledger
   (`.codex-orchestrator/runs/<id>/`), not just in conversation.

## Repo layout

```
.claude-plugin/   plugin.json (v0.4.1), marketplace.json
commands/         thin slash-command triggers that load skills
skills/           orchestrate/, workflow/, report/ playbooks and orchestration references
monitors/         monitors.json
bin/              codex-orch, codex-orch-monitor
templates/        task-prompt.md, review-prompt.md
scripts/          codex_orchestrator/ (the package: cli, gate, ledger, parse, report, contract, …);
                  codex_orch.py + codex_orch_parse.py are thin path-invoked CLI entry points
schemas/          codex-orchestrator.schema.json, codex-task-output.schema.json
bench/            deterministic replay self-test; external benchmarks live in codex-orchestrator-bench
tests/            unittest suite
docs/             maintainer docs
```

## Common commands

```bash
# Tests (must stay green; add coverage with changes)
python3 -m unittest discover -s tests -v

# Deterministic protocol benchmark (no models/API — CI-friendly)
python3 -m bench.run --suite replay

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

## Public status

`main` is the held benchmark baseline; development lands on integration branches; releases are
tagged (`v0.2.0`, `v0.3.5`, `v0.4.0`, `v0.4.1`). Benchmark results are in
`docs/benchmarks.md`; external benchmark machinery lives in the
[`codex-orchestrator-bench`](https://github.com/alexzh3/codex-orchestrator-bench) repo.

## Versioning policy

Stay on the **0.3.x/0.4.x** lines — patch releases bump the patch
(0.3.1, 0.3.2, …; 0.4.1, …). Do not bump beyond 0.4.x without explicit instruction.

## How to extend

- **A ledger event type:** add the `$def` to `schemas/codex-orchestrator.schema.json`, mirror enums
  in `scripts/codex_orchestrator/contract.py`, add validation in the `codex_orchestrator` package,
  render it in `scripts/codex_orchestrator/report_render.py`, and extend `tests/test_schema.py` + a
  focused test.
- Always run the full unittest suite + the relevant `bench.run` before proposing changes.
