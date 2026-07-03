# TBLite head-to-head benchmark bundle

Self-contained reproducibility bundle for the OpenThoughts-TBLite head-to-head across plugin
versions **0.2.0 / 0.3.4 / 0.3.5**. Results are written to
[`../../docs/benchmark-results-tblite-headtohead.md`](../../docs/benchmark-results-tblite-headtohead.md).

## Contents
- `probe_tblite.py` — run ONE `(task, plugin_ref)` cell through the real Harbor path
  (`bench.harbor_agent` + `bench.adapters.tblite`); writes a result artifact, fails loudly on a
  session/rate-limit (0-token) run so it is never recorded as a real result.
- `run_matrix.sh` — drive the full matrix (10 hardest tasks × 3 versions). **Resumable**: skips any
  cell whose artifact already exists; one failed cell never aborts the run.
- `aggregate_results.py` — regenerate the results doc from `artifacts/` (idempotent).
- `artifacts/probe-*.json` — the 30 raw per-cell results (metrics only; no secrets).

## Run
```bash
# prereqs: docker running; harbor installed + `harbor download openthoughts-tblite`;
#          ~/.codex/auth.json present; CLAUDE_CODE_OAUTH_TOKEN in repo-root ./.env (gitignored)
bash    bench/tblite_headtohead/run_matrix.sh          # runs cells (resumable)
python3 bench/tblite_headtohead/aggregate_results.py   # regenerates the doc
```

## Notes
- Models: orchestrator = Claude Opus-4.8 @ max effort; implementer = Codex gpt-5.5 @ xhigh.
- Claude auth is **token mode** (`CLAUDE_CODE_OAUTH_TOKEN`) — the reuse-login credentials file is
  not read inside the container.
- One session window fits ~14 heavy runs before the subscription limit; the matrix spans several
  windows and resumes automatically.
- RExBench is deferred (GPU-gated); see the results doc for the per-task classification.
