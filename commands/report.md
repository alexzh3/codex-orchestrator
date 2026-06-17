---
description: Generate or update report.md from state and ledger evidence after review work is complete.
---

# Report

Use this command to close a run with durable evidence.

Use when: verification evidence and any consensus decisions have already been recorded and you want
a human-readable `report.md` for handoff or approval.

Do not use when: you still need to monitor Codex or review the diff. Use
`/codex-orchestrator:workflow` for active orchestration phases, including monitoring, review,
consensus, handoff, and compute gating.

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

The final report should summarize accepted changes, verification evidence, unresolved risks, and
every recorded consensus decision.

Reference:

```text
skills/codex-orchestrator/SKILL.md
```
