# Report

Use this command to close a run with durable evidence.

Scope: report generation. This command assumes review and verification evidence have already been
recorded in `ledger.jsonl`; it should not perform the full orchestration workflow by itself.

Update these files under `.codex-orchestrator/runs/<run-id>/`:

```text
state.json
ledger.jsonl
report.md
```

Default command:

```bash
python3 scripts/codex_orch.py report --run-id <run-id>
```

The final report should summarize accepted changes, verification evidence, unresolved risks, and every recorded consensus decision. Follow `skills/codex-orchestrator/SKILL.md` sections 4 and 8.
