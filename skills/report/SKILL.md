---
name: codex-orchestrator-report
description: Generate or update report.md from recorded state, monitor events, verification, and consensus evidence.
---

# Report

Use this skill to close a run with durable evidence after review, verification, and any consensus
decisions have already been recorded.

Do not use this skill to start Codex agents, monitor Codex, or review a diff. Use
`${CLAUDE_PLUGIN_ROOT}/skills/orchestrate/SKILL.md` for focused orchestration phases and
`${CLAUDE_PLUGIN_ROOT}/skills/workflow/SKILL.md` for the full end-to-end run.

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
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/codex_orch.py" report --strict --run-id <run-id>
```

The report should stay compact. The compiler emits authored `Summary` and `Changes`, plus generated
`Evidence`, `Consensus`, `Risks / Follow-ups`, `Reproducibility`, `Task Graph`, and `Gate Result`.
The report helper preserves authored sections while regenerating evidence from durable records.

Reference: `${CLAUDE_PLUGIN_ROOT}/skills/orchestrate/SKILL.md`.
