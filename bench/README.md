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

Tiered runs use frozen task ids from `bench/tiers.json` schema v2. The active
tiers are `tiny` and `frontier`; the old `normal` tier was removed. Dry-run mode
is deterministic and does not call Claude, Codex, Docker, Harbor, network
services, external graders, or local descriptor files:

```bash
python3 -m bench.run --tier tiny --plugin-ref demo --dry-run
python3 -m bench.run --tier frontier --plugin-ref demo --dry-run
```

Current frozen contents:

| Tier | Benchmark | Count | Status | Issue |
|------|-----------|-------|--------|-------|
| `tiny` | `tblite` | 10 | runnable | #3 |
| `frontier` | `terminalbench_2_1` | 8 | adapter_pending | #18 |
| `frontier` | `swebench_pro_public` | 3 | adapter_pending | #18 |
| `frontier` | `rexbench` | 6 | external_grading_only | #10 |

Real mode is the infra-gated layer. For runnable slots it runs
`claude -p --plugin-dir <ref>` through the orchestrator workflow and spends
Claude+Codex budget. The adapters only read local dataset files; they do not
download datasets or install graders. If a dataset or grader is missing, real
mode raises a clear `RuntimeError` naming the env var, expected layout, required
infra, and tracking issue. Frontier real mode is currently gated and exits
nonzero without emitting placeholder result records. External real-mode tasks
run in the benchmark target repository, not in this plugin repository. The
plugin repository is still used as `--plugin-dir`.

Benchmark result records may include a top-level `token_usage` object with
`input_tokens`, `output_tokens`, `cache_read_input_tokens`,
`cache_creation_input_tokens`, `total_tokens`, `cost_usd`, and
`num_turns_reported`. Real runs source these values from Claude's
`--output-format stream-json` terminal `result` event (`total_cost_usd` becomes
`cost_usd`); fields are `null` when unavailable, including dry-run, timeouts,
or streams without usage data. Local-mini and tier runs also print a summary
line:

```text
Summary tokens: input=<n> output=<n> total=<n> cost_usd=<f>
```

Each task descriptor may provide:

- `id`, `task_id`, or `instance_id`
- `prompt`, `instructions`, `problem_statement`, or `description`
- `success_rate`, `pass_rate`, `solve_rate`, or `baseline_success_rate` for
  lowest-success-rate selection
- `difficulty`, `difficulty_score`, or `difficulty_band` as the fallback sort
- `files_allowed` for the runner allowlist; defaults to `*` and `**/*`
- `acceptance.command` or `grader_command` for the external grader command
- optional run controls: `start_ref`, `timeout_seconds`, `max_budget_usd`,
  and `max_turns`
  - `max_budget_usd` is forwarded to real `claude` as `--max-budget-usd`
  - `max_turns` only bounds the simulated `claude_turns` count in dry-run
    mode; it is not forwarded to real `claude` because the CLI exposes no
    turn-limit flag
- target checkout fields for real external runs:
  - `target_repo_path`: local clone to use directly; relative paths resolve
    from the dataset directory
  - `base_commit`: preferred target checkout ref, such as a SWE-bench base
    commit
  - `repo_url`: repository URL used to locate a prepared local clone
  - `repo`: repository identifier or local path, such as `owner/name`
  - `instance_id` and `environment_setup_commit`: preserved for SWE-bench
    descriptors and grader command placeholders

When `target_repo_path` is absent, `repo_url` or `repo` can be resolved through
`CODEX_ORCH_BENCH_REPO_CACHE`, which must point at a directory containing
prepared local clones. The resolver checks common cache names such as
`owner/name`, `owner__name`, the repository basename, and a stable safe name. If
an external task declares a target that cannot be resolved or checked out, real
mode raises `NotImplementedError` or `RuntimeError`; it never falls back to
running the task in the plugin repository.

Grader commands run from the temporary target worktree created by the runner.
They may use `{task_id}`, `{id}`, `{case_id}`, `{work_dir}`, and
`{dataset_dir}` placeholders.

The descriptor-driven `iter_tasks` selection path is still available for
ad-hoc/bootstrap use. Tier runs use `resolve_frozen_tasks`, which resolves the
fixed ids from `bench/tiers.json` and verifies descriptor hashes in real mode.

### RExBench

- Dataset env var: `REXBENCH_DIR`
- Default path: `bench/datasets/rexbench`
- Supported local task files: `tasks.jsonl`, `tasks.json`, `rexbench.jsonl`,
  or `rexbench.json` at the dataset root
- Grader command env var: `REXBENCH_GRADER_CMD`
- Required infra: external patch-ZIP submission through rexbench.com; no local
  pass/fail grader exists or is possible. Local GPU execution is also blocked by
  the benchmark env pinning torch <=2.6, incompatible with sm_120.
- Tracking issue: #10

Example:

```bash
export REXBENCH_DIR=/data/rexbench
python3 -m bench.run --tier frontier --plugin-ref release/0.3.4  # gated external grading
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

### Terminal-Bench 2.1

- Dataset env var: `TB21_DIR`
- Default path: `bench/datasets/terminalbench_2_1`
- Required infra: Harbor with dataset `terminal-bench/terminal-bench-2-1`
- Tier status: `adapter_pending`
- Tracking issue: #18

Dry-run works through the base frozen-task path. Real tier runs are gated until
the adapter is implemented.

### SWE-bench Pro Public

- Dataset env var: `SWEBENCH_PRO_DIR`
- Default path: `bench/datasets/swebench_pro_public`
- Required infra: SWE-bench Pro Docker evaluator plus `jefzda/sweap-images`
- Tier status: `adapter_pending`
- Tracking issue: #18

Dry-run works through the base frozen-task path. Real tier runs are gated until
the adapter is implemented.

### SWE-bench Verified Mini

SWE-bench Verified Mini is no longer included in `bench/tiers.json`, but the
adapter is retained for ad-hoc runs.

- Dataset env var: `SWEBENCH_VERIFIED_MINI_DIR`
- Default path: `bench/datasets/swebench_verified_mini`
- Supported local task files: `instances.jsonl`, `instances.json`,
  `tasks.jsonl`, or `tasks.json` at the dataset root
- Grader command env var: `SWEBENCH_VERIFIED_MINI_GRADER_CMD`
- Required infra: Docker-enabled SWE-bench evaluator with the Verified Mini
  subset present locally
- Tracking issue: #2

There is no frozen tier command for this adapter; use it from focused scripts or
tests when an ad-hoc Verified Mini run is needed.
