---
name: codex-orchestrator-orchestrate
description: Orchestrate, monitor, review, and coordinate Codex agents and IDE sessions from Claude Code.
---

# Claude-Codex Orchestration

Claude plans, coordinates, and verifies. Codex handles scoped implementation and review in its
native CLI or IDE harness. Prefer Codex as the first mover for bounded coding tasks.

Use this skill for a focused orchestration phase. Use
`${CLAUDE_PLUGIN_ROOT}/skills/workflow/SKILL.md` for a complete run and
`${CLAUDE_PLUGIN_ROOT}/skills/report/SKILL.md` only after closure.

## Durable Run

Keep run material under:

```text
.codex-orchestrator/runs/<run-id>/
  journal.jsonl
  agents/<provider>-<role>-<NN>/execution-<NN>/
    prompt.md
    events.jsonl
    handoff.md
  evidence/                 # optional
  report.md                 # after run_closed
```

`journal.jsonl` is Claude's append-only orchestration journal. Read
`${CLAUDE_PLUGIN_ROOT}/docs/orchestration-contract.md` before creating or interpreting journal
entries; it owns record fields, authority, validation, and closure semantics.

Capture each execution's exact prompt, raw events when available, and exact handoff. Never
synthesize a log or rewrite a handoff. Keep small observations inline and create `evidence/` only
when material output must be retained.

## Standard Loop

1. Create the run directory and append `run_started` before task work.
2. Append active `task` entries with goals, acceptance criteria, and allowed/owned `files`.
3. Compare task files and shared resources before parallel work; serialize overlap or use a
   worktree.
4. Reuse a relevant agent or create a named one. Use a fresh agent and native session for an
   initial independent review or unanchored alternative.
5. Save the exact prompt and append `execution` before launch.
6. Monitor with the bundled session tools without editing files owned by the active agent.
7. Save the exact handoff, inspect it and the repository, then append terminal
   `execution_result`.
8. Evaluate acceptance criteria and record material checks as `verification`.
9. Record only consequential resolutions or user dependencies as `decision`.
10. Append a terminal `task` entry after its acceptance criteria are evaluated.
11. When no work remains, use the workflow skill to validate and close the run, then invoke the
    report skill.

Validation detects structural omissions; Claude decides acceptance.

## Reference Map

Read only what the current phase needs:

- `references/monitoring.md`: execution capture, CLI and IDE monitoring, and handoffs.
- `references/review.md`: verification and independent review.
- `references/consensus.md`: consensus and decision outcomes.
- `references/compute.md`: parallel ownership, worktrees, and compute gating.
