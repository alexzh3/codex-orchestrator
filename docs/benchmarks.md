# External Benchmark Dataset Preparation

`bench/prepare_datasets.py` provisions local descriptor files for the external
benchmark adapters. The script uses only the Python standard library for core
fetching and conversion.

```bash
python3 bench/prepare_datasets.py --dry-run
python3 bench/prepare_datasets.py --benchmark swebench_verified_mini --limit 50
python3 bench/prepare_datasets.py --benchmark tblite --limit 15
python3 bench/prepare_datasets.py --benchmark rexbench
```

Output is written under `bench/datasets/<name>/`, which is gitignored. The
adapters also accept the corresponding dataset env vars documented in
`bench/README.md`.

## Sources And Ranking

SWE-bench Verified Mini is derived from
`princeton-nlp/SWE-bench_Verified` test rows fetched through the Hugging Face
datasets-server. The preparer keeps only the one-hour-plus bands
(`1-4 hours` and `>4 hours`), maps them to numeric `difficulty_score` values,
sorts hardest first, and writes
`bench/datasets/swebench_verified_mini/instances.jsonl`. It also writes
`repos.txt` containing the selected `repo@base_commit` pairs for pre-cloning
into `CODEX_ORCH_BENCH_REPO_CACHE`.

OpenThoughts-TBLite is read from
`open-thoughts/OpenThoughts-TBLite` task directories. The preparer fetches each
`task.toml` and `instruction.md`, maps the metadata difficulty band to
`difficulty_score`, uses `expert_time_estimate_min` as a tiebreaker, and writes
`bench/datasets/tblite/tasks.jsonl`. Real execution still requires
Harbor/Docker and the native TBLite runner work tracked by #3/#18.

RExBench is gated at `tin-lab/RExBench`. The preparer downloads `dataset.zip`,
extracts it into the gitignored output directory, fetches
`instructions/<task>/instructions.md`, and writes
`bench/datasets/rexbench/tasks.jsonl`. If bundled per-task metadata exposes a
difficulty signal, it is converted into `difficulty_score`; otherwise tasks are
kept in stable id order. Real execution still requires the RExBench executor
tracked by #10/#18.

## Privacy

RExBench gating requires that agent outputs are not made public to avoid data
leakage. Do not commit, push, publish, or attach RExBench data, instructions,
prepared descriptors, worktrees, logs, or agent outputs. The default output
directory is gitignored for this reason.

## Execution Status

The prepared descriptors include explicit failing grader placeholders naming the
required native harnesses. SWE-bench descriptors carry `repo` and `base_commit`
fields, so target checkout fits the existing git-worktree adapter path; grading
still requires a Docker-enabled SWE-bench evaluator (#2/#18). TBLite and
RExBench descriptors need their native external runners before real benchmark
results are meaningful (#18).
