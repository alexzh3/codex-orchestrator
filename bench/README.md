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
