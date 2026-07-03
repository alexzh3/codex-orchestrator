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
`bench/datasets/tblite/tasks.jsonl`.

RExBench is gated at `tin-lab/RExBench`. The preparer downloads `dataset.zip`,
extracts it into the gitignored output directory, fetches
`instructions/<task>/instructions.md`, and writes
`bench/datasets/rexbench/tasks.jsonl`. If bundled per-task metadata exposes a
difficulty signal, it is converted into `difficulty_score`; otherwise tasks are
kept in stable id order. RExBench grading is external-only: patch ZIPs are
submitted through rexbench.com for async email/leaderboard results. No local
pass/fail grader exists or is possible (#10).

## Frozen Tiers (Schema V2)

`bench/tiers.json` is schema v2 and freezes explicit task ids instead of
dynamic `count` plus `lowest_success_rate` slots. This keeps head-to-head runs
repeatable. The old dynamic selection path remains in adapter `iter_tasks` and
in `bench/prepare_datasets.py`, but it is now bootstrap/discovery behavior only.
That matters especially for RExBench, where dynamic ranking degraded to stable
alphabetical order when no success-rate field was available.

Bootstrap flow:

1. Prepare local descriptors with `bench/prepare_datasets.py`.
2. Rank or inspect candidate tasks using descriptor metadata and prior runs.
3. Run the candidate set once.
4. Freeze the survivors as ids, reasons, provenance pins, and descriptor hashes.

For descriptors available locally, each frozen task stores the sha256 of the raw
descriptor row canonicalized as sorted compact JSON. Real frozen runs verify
that hash before normalization. Missing ids or hash drift fail loudly; re-freezing
`bench/tiers.json` is a deliberate documented act, not an automatic repair.
Slots without local descriptors carry `sha256: null` and pin the source revision
instead.

Current tiers:

| Tier | Contents | Status |
|------|----------|--------|
| `tiny` | 10 frozen OpenThoughts-TBLite tasks | runnable through Harbor/TBLite real mode |
| `frontier` | 8 Terminal-Bench 2.1 tasks | `adapter_pending`, #18 |
| `frontier` | 3 SWE-bench Pro public tasks | `adapter_pending`, #18 |
| `frontier` | 6 RExBench tasks | `external_grading_only`, #10 |

The old `normal` tier was removed. `swebench_verified_mini` is no longer part of
any tier, but its adapter remains available for ad-hoc runs.

### Recorded Baseline (2026-07-03)

The frozen `tiny` design set comes from 30/30 completed TBLite head-to-head
cells. Per-version pass counts were 0.2.0: 7/10, 0.3.4: 6/10, and 0.3.5: 6/10.
Real-orchestration rate improved 8/10 -> 9/10 -> 10/10, while genuinely
orchestrated passes, defined as passed and dispatched Codex, tied at 6/10 for
all three versions. Claude `cost_usd` is sparse in Harbor, so summed Claude
input tokens are the cost proxy: 24.98M, 18.51M, and 27.09M respectively.

This is a design set frozen for comparability, not a difficulty population
estimate. Each cell has one run, so directional conclusions need caution. Full
tables are in `docs/benchmark-results-tblite-headtohead.md`.

## Privacy

RExBench gating requires that agent outputs are not made public to avoid data
leakage. Do not commit, push, publish, or attach RExBench data, instructions,
prepared descriptors, worktrees, logs, or agent outputs. The default output
directory is gitignored for this reason.

## Execution Status

The prepared descriptors include explicit failing grader placeholders naming the
required native harnesses where the real runner is not wired. SWE-bench
Verified Mini descriptors carry `repo` and `base_commit` fields, so target
checkout fits the existing git-worktree adapter path; grading still requires a
Docker-enabled SWE-bench evaluator (#2). Terminal-Bench 2.1 and SWE-bench Pro
public are frozen frontier slots with adapter work pending (#18). RExBench is
external-grading-only via rexbench.com (#10).

## Real OpenThoughts-TBLite Runs

TBLite real mode uses Harbor/Docker. Each selected task runs the custom Harbor
agent at `bench.harbor_agent:CodexOrchestratorAgent`, which installs Claude Code
and Codex in the task container, uploads the local plugin directory, and invokes
Claude as:

```bash
claude --verbose --output-format=stream-json --effort max --plugin-dir /tmp/codex-orch-plugin --print -- "/codex-orchestrator:orchestrate <task instruction>"
```

The agent forces `claude-opus-4-8` through Harbor ClaudeCode's `ANTHROPIC_MODEL`
environment path and forces reasoning effort `max` through the ClaudeCode
`--effort` flag. Harbor may still pass `-m` or agent kwargs, but this agent
overrides them. Plugin-dispatched Codex sessions use the in-container
`$CODEX_HOME/config.toml` and `~/.codex/config.toml`:

```toml
model = "gpt-5.5"
model_reasoning_effort = "xhigh"
service_tier = "default"
```

Override those Codex defaults with `CODEX_ORCH_CODEX_MODEL`,
`CODEX_ORCH_CODEX_REASONING_EFFORT`, or `CODEX_ORCH_CODEX_SERVICE_TIER`.

Claude authentication has two modes, selected by `CODEX_ORCH_CLAUDE_AUTH_MODE`:

- **`credentials` (default) — reuse your local `claude login`.** The agent uploads
  `~/.claude/.credentials.json` verbatim into each local container (the same
  pattern as Codex `auth.json`); the file is never parsed or logged. This reuses
  the operator's Claude subscription, including the refresh token, so no separate
  headless token is needed. `ANTHROPIC_API_KEY` is blanked inside the container so
  the CLI prefers that subscription credentials file over any stray API key.
  Override the source path with `CODEX_ORCH_CLAUDE_CREDENTIALS_FILE`.
- **`token` — headless OAuth token.** Set `CODEX_ORCH_CLAUDE_AUTH_MODE=token`,
  run `claude setup-token`, and export `CLAUDE_CODE_OAUTH_TOKEN`. This mints a
  long-lived token that will not expire mid-campaign — preferred for large runs.

Host prerequisites (credentials mode, the default):

```bash
test -f ~/.claude/.credentials.json   # produced by `claude login`
test -f ~/.codex/auth.json
export CODEX_FORCE_AUTH_JSON=1
docker info
harbor download openthoughts-tblite
```

Direct Harbor smoke command (credentials mode):

```bash
cat >/tmp/codex-orch-tblite.env <<EOF
CODEX_ORCH_PLUGIN_DIR=/path/to/codex-orchestrator
CODEX_ORCH_CLAUDE_AUTH_MODE=credentials
ANTHROPIC_API_KEY=
CODEX_FORCE_AUTH_JSON=1
EOF

harbor run -d openthoughts-tblite -i <task-id> \
  --agent-import-path bench.harbor_agent:CodexOrchestratorAgent \
  -n 1 -o jobs/tblite-real --env-file /tmp/codex-orch-tblite.env
```

For token mode instead, drop `CODEX_ORCH_CLAUDE_AUTH_MODE`/`ANTHROPIC_API_KEY`
and set `CODEX_ORCH_CLAUDE_AUTH_MODE=token`, `CLAUDE_FORCE_OAUTH=1`, and
`CLAUDE_CODE_OAUTH_TOKEN=<token from claude setup-token>` in the env file.

The benchmark helper writes the env file for the real tier path so secrets do
not appear in argv:

```bash
python3 -m bench.run --tier tiny --plugin-ref /path/to/codex-orchestrator
```

Set `TBLITE_HARBOR_DATASET` to override the Harbor dataset name; the default is
`openthoughts-tblite`. Grading comes only from Harbor's verifier reward in the
task result JSON. Each normalized result also reports
`codex_sessions_spawned` and `real_orchestration` by parsing the collected
`claude-code.txt` trajectory for real `codex exec` Bash dispatches. A solved
run with zero Codex dispatches is recorded honestly and marked
`degenerate_no_codex` in `external_score` rather than silently changing
pass/fail.

Each real TBLite task also reports `external_score.token_breakdown` with
Claude orchestrator usage, GPT/Codex implementer usage, and a combined total.
The Claude side comes from Harbor's `agent_result` or `stats`. The GPT/Codex
side is parsed from Codex session JSONL collected out of the task container:
after Claude returns, the custom Harbor agent copies `$CODEX_HOME/sessions`
from `/tmp/codex-home` into the `/logs/agent/codex-sessions` bind mount, so the
session rollouts appear in the Harbor job directory. It also best-effort copies
other non-session `$CODEX_HOME/**/*.jsonl` streams under that collected tree.
GPT-side `cost_usd` is not available from those Codex logs and is reported as
`null`, never estimated.

If Harbor, Docker, the downloaded dataset, Claude OAuth, or Codex `auth.json`
are missing, real mode raises instead of emitting placeholder pass/fail
results.
