---
description: Resolve a Claude-Codex disagreement about a suspected bug, fix, or implementation direction using evidence.
---

# Consensus

Use this command when Claude and Codex disagree about a suspected bug, fix, or implementation direction.

Use when: Claude finds a concrete issue in Codex output, Codex challenges Claude's finding, or the
fix direction is ambiguous enough to require a recorded evidence-based decision.

Do not use when: there is no disagreement or suspected mistake. Record ordinary checks with
`/codex-orchestrator:review` instead.

Default paths:

```bash
"$CODEX" exec review --uncommitted
"$CODEX" exec resume <thread-id> "<specific finding and proposed fix>"
```

Record the finding, evidence, root cause when known, and agreed resolution as a `consensus` record in `.codex-orchestrator/runs/<run-id>/ledger.jsonl` and in the `## Consensus` section of `.codex-orchestrator/runs/<run-id>/report.md`. Follow `skills/codex-orchestrator/SKILL.md` section 8.
