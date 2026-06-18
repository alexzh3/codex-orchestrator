---
description: Generate or update report.md from recorded state, monitor events, verification, and consensus evidence.
---

# Report

Use this command to close a run with durable evidence.

Use when: verification evidence and any consensus decisions have already been recorded and you want
a human-readable `report.md` for handoff or approval.

Do not use when: you still need to start Codex agents, monitor Codex, or review the diff. Use
`/codex-orchestrator:orchestrate` for prompt-directed orchestration phases, including monitoring,
review, consensus, handoff, and compute gating. Use `/codex-orchestrator:workflow` only for the full
end-to-end run.

Scope: report generation. This command assumes review and verification evidence have already been
recorded in `ledger.jsonl`; it should not perform the full orchestration workflow by itself.
`Summary` and `Changes` are authored handoff sections and must be preserved when regenerating the
report. `Evidence`, `Consensus`, and `Risks / Follow-ups` are generated from durable records.

Read these files under `.codex-orchestrator/runs/<run-id>/`:

```text
state.json
ledger.jsonl
```

Update this file:

```text
report.md
```

Default command:

```bash
python3 scripts/codex_orch.py report --run-id <run-id>
```

The final report should stay compact: authored `Summary` and `Changes`, generated `Evidence`,
generated `Consensus`, and generated `Risks / Follow-ups`.

Reference:

```text
commands/orchestrate.md
```
