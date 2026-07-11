---
name: codex-orchestrator-orchestrate
description: Orchestrate, monitor, review, and coordinate Codex agents from Claude Code.
---

# Claude-Codex Orchestration

Claude plans, coordinates, and verifies. Codex handles scoped implementation and review through
its native CLI. Prefer Codex as the first mover for bounded coding tasks.

This skill owns the run protocol. Use it for focused orchestration and consult its references only
for the current phase. The workflow skill applies this protocol to a complete run and adds closure
and reporting.

## Durable Run

Keep run material under:

```text
.codex-orchestrator/runs/<run-id>/
  journal.jsonl
  <provider>-<role>-<NN>/execution-<NN>/
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
4. Reuse a relevant agent or create a named one. Start an independent review in a fresh agent and
   native session. For a consequential design choice, ask a fresh Codex agent to propose an
   approach from only the goal, constraints, and acceptance criteria before showing it Claude's
   candidate, then compare both against evidence.
5. Save the exact prompt and append `execution` before launch.
6. Monitor with the bundled session tools without editing files owned by the active agent.
7. Save the exact handoff, inspect it and the repository, then append terminal
   `execution_result`.
8. Evaluate acceptance criteria and record material checks as `verification`.
9. Record only consequential resolutions or user dependencies as `decision`.
10. Append a terminal `task` entry after its acceptance criteria are evaluated.
11. When no work remains, validate and close the run as directed by the workflow skill, then invoke
    the report skill.

Routine bounded work needs Codex implementation plus Claude verification. Add a fresh reviewer only
for material risk or a distinct unresolved question; do not repeat identical reviews.

Validation detects structural omissions; Claude decides acceptance.

## Reference Map

Read only what the current phase needs:

- `references/monitoring.md`: execution capture, CLI monitoring, and handoffs.
- `references/review.md`: verification and independent review.
- `references/consensus.md`: consensus and decision outcomes.
- `references/compute.md`: parallel ownership, worktrees, and compute gating.
