# Codex Orchestrator Benchmarks

This directory contains deterministic benchmark harnesses that exercise the local
orchestrator artifacts without calling Claude, Codex, network services, or APIs.

## Replay Suite

Run the Layer 1 replay suite:

```bash
python3 -m bench.run --suite replay
```

Refresh golden reports after an intentional renderer change:

```bash
python3 -m bench.run --suite replay --update-golden
```

Write benchmark result records only when an output path is supplied:

```bash
python3 -m bench.run --suite replay --out /tmp/replay-results.jsonl
```

Compare two JSON or JSONL result sets:

```bash
python3 -m bench.compare --baseline /tmp/baseline.jsonl --candidate /tmp/candidate.jsonl
```

## Tiered External Benchmarks

Tiered runs use the external adapters for RExBench, OpenThoughts-TBLite,
and SWE-bench Verified Mini. Dry-run mode is deterministic and does not call
Claude, Codex, Docker, Harbor, network services, or external graders:

```bash
python3 -m bench.run --tier tiny --plugin-ref demo --dry-run
python3 -m bench.run --tier normal --plugin-ref demo --dry-run
```

Real mode is the infra-gated layer. It runs `claude -p --plugin-dir <ref>`
through the orchestrator workflow and spends Claude+Codex budget. The adapters
only read local dataset files; they do not download datasets or install graders.
If a dataset or grader is missing, real mode raises a clear `RuntimeError`
naming the env var, expected layout, required infra, and tracking issue.

Each task descriptor may provide:

- `id`, `task_id`, or `instance_id`
- `prompt`, `instructions`, `problem_statement`, or `description`
- `success_rate`, `pass_rate`, `solve_rate`, or `baseline_success_rate` for
  lowest-success-rate selection
- `difficulty`, `difficulty_score`, or `difficulty_band` as the fallback sort
- `files_allowed` for the runner allowlist; defaults to `*` and `**/*`
- `acceptance.command` or `grader_command` for the external grader command
- optional `start_ref`, `timeout_seconds`, `max_turns`, and `max_budget_usd`

Grader commands run from the temporary target worktree created by the runner.
They may use `{task_id}`, `{id}`, `{case_id}`, `{work_dir}`, and
`{dataset_dir}` placeholders.

### RExBench

- Dataset env var: `REXBENCH_DIR`
- Default path: `bench/datasets/rexbench`
- Supported local task files: `tasks.jsonl`, `tasks.json`, `rexbench.jsonl`,
  or `rexbench.json` at the dataset root
- Grader command env var: `REXBENCH_GRADER_CMD`
- Required infra: local RExBench dataset plus the RExBench executor/grader
- Tracking issue: #10

Example:

```bash
export REXBENCH_DIR=/data/rexbench
export REXBENCH_GRADER_CMD='rexbench evaluate --task-id {task_id} --workspace .'
python3 -m bench.run --tier tiny --plugin-ref release/0.3.4
```

### OpenThoughts-TBLite

- Dataset env var: `TBLITE_DIR`
- Default path: `bench/datasets/tblite`
- Supported local task files: `tasks.jsonl`, `tasks.json`, `tblite.jsonl`,
  or `tblite.json` at the dataset root
- Grader command env var: `TBLITE_GRADER_CMD`
- Required infra: Harbor with OpenThoughts-TBLite/Terminal-Bench tasks and
  grader available locally
- Tracking issue: #3

Example:

```bash
export TBLITE_DIR=/data/openthoughts-tblite
export TBLITE_GRADER_CMD='harbor grade --task-id {task_id} --workspace .'
python3 -m bench.run --tier tiny --plugin-ref release/0.3.4
```

### SWE-bench Verified Mini

- Dataset env var: `SWEBENCH_VERIFIED_MINI_DIR`
- Default path: `bench/datasets/swebench_verified_mini`
- Supported local task files: `instances.jsonl`, `instances.json`,
  `tasks.jsonl`, or `tasks.json` at the dataset root
- Grader command env var: `SWEBENCH_VERIFIED_MINI_GRADER_CMD`
- Required infra: Docker-enabled SWE-bench evaluator with the Verified Mini
  subset present locally
- Tracking issue: #2

Example:

```bash
export SWEBENCH_VERIFIED_MINI_DIR=/data/swebench-verified-mini
export SWEBENCH_VERIFIED_MINI_GRADER_CMD='swebench evaluate --instance-id {task_id} --workspace .'
python3 -m bench.run --tier normal --plugin-ref release/0.3.4
```
