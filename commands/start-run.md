---
description: Create the compact durable run ledger only; no Codex subagents, monitors, review, or report generation.
---

# Start Run

Use this command to open a durable run ledger before dispatching or supervising Codex.

Use when: you need only this setup step before starting manual orchestration:

```text
create .codex-orchestrator/runs/<run-id>/
  state.json
  ledger.jsonl
  report.md
```

Do not use when: you want Claude to perform the whole workflow. Use `/codex-orchestrator:workflow`
for the end-to-end run.

Scope: setup only. This is the "open a run ledger" command. It should create the compact runtime
files and stop; it should not start Codex exec subagents, monitor Codex, run tests, review diffs,
resolve consensus, or generate the final report. Use `/codex-orchestrator:workflow` for the full
end-to-end workflow.

Default path:

```bash
python3 scripts/codex_orch.py init --repo . --run-id <run-id>
```

Reference:

```text
skills/codex-orchestrator/SKILL.md
```
