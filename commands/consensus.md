# Consensus

Use this command when Claude and Codex disagree about a suspected bug, fix, or implementation direction.

Default paths:

```bash
"$CODEX" exec review --uncommitted
"$CODEX" exec resume <thread-id> "<specific finding and proposed fix>"
```

Record the finding, evidence, root cause when known, and agreed resolution as a `consensus` record in `.codex-orchestrator/runs/<run-id>/ledger.jsonl` and in the `## Consensus` section of `.codex-orchestrator/runs/<run-id>/report.md`. Follow `skills/codex-orchestrator/SKILL.md` section 8.
