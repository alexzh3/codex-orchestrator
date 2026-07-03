# Replay Benchmark

This directory keeps the deterministic replay self-test for the plugin.

The replay suite locks the orchestration protocol's generated report and score behavior
byte-for-byte. It does not call Claude, Codex, external graders, Docker, Harbor, network services,
or APIs.

Run it with:

```bash
python3 -m bench.run --suite replay
```

The golden fixture is `bench/cases/replay/long-run-001/`: a fixed state file, ledger, case metadata,
and expected report used to catch renderer, parser, and scoring drift.

Use `--update-golden` only after an intentional report/score behavior change and a human review of
the generated diff. Do not use it during normal work.

External benchmarks, raw artifacts, aggregation tooling, and run instructions live in
[`codex-orchestrator-bench`](https://github.com/alexzh3/codex-orchestrator-bench).
