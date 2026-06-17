# Consensus

Use this command when Claude and Codex disagree about a suspected bug, fix, or implementation direction.

Default paths:

```bash
"$CODEX" exec review --uncommitted
"$CODEX" exec resume <thread-id> "<specific finding and proposed fix>"
```

Record the finding, evidence, root cause when known, and agreed resolution in `.codex-orchestrator/runs/<run-id>/consensus.md`. Follow `skills/codex-orchestrator/SKILL.md` section 8.
