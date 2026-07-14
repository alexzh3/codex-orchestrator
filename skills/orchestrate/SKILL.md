---
name: codex-orchestrator-orchestrate
description: Run a focused Codex-agent planning, implementation, monitoring, review, or verification phase.
---

# Claude-Codex Orchestration

Claude coordinates and verifies focused agent work. Codex handles scoped implementation and review
and can provide optional planning input through its native CLI. Prefer Codex as the first mover for
bounded coding tasks; Claude retains final planning and acceptance authority.

Use this skill for one focused agent cycle inside an orchestration run. The workflow skill owns
planning, run initialization, task decomposition, closure, and reporting. Return to it when the
focused phase is complete.

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

## Roles And Performance Policy

Use only the canonical role and matching persistent-agent prefix for new Codex executions:

| Role | Agent prefix | Use |
| --- | --- | --- |
| `implementation` | `codex-impl-NN` | Implement scoped work and resume focused fixes. |
| `review` | `codex-review-NN` | Independently review implementation work. |
| `planning` | `codex-plan-NN` | Optionally propose an independent approach. |
| `planning_review` | `codex-plan-review-NN` | Optionally critique Claude's draft plan. |

When `.codex-orchestrator/config.ini` exists, inspect the role with `config show`, select one
allowed reasoning effort using the workflow rubric, and pass that concrete selection to the
runner. Record the selected `effort` and any policy-supplied `model` and `service_tier` in
`execution` before launch. Reselect effort for a resume because the next prompt may have different
breadth or context needs.

When the file is absent, still pass repository and role metadata to the runner but omit
`--reasoning-effort`; the runner must not create configuration or alter the child Codex command.
Never silently change a configured model, effort, or service tier after a compatibility or
entitlement failure.

## Focused Agent Cycle

1. Read the complete journal, current task, and relevant references before acting.
2. Confirm the task's acceptance criteria and allowed/owned `files`.
3. Compare active task files and shared resources before parallel work; serialize overlap or use a
   worktree.
4. Reuse a relevant agent or create a named one. For an independent review, start a fresh agent and
   native session. Planning and plan-review passes are also fresh, mutually separate, read-only
   sessions; do not resume either from an implementation, review, or one another.
5. Resolve the execution's role policy, absolute worktree, full HEAD, and attached branch when
   present and include them in its record.
   Save the exact prompt and append `execution` before launch.
6. Monitor with the bundled tools without editing files owned by the active agent.
7. Save the exact handoff, inspect it and the repository, then append terminal
   `execution_result`.
8. Evaluate acceptance criteria and record material checks as `verification`.
9. Record only consequential resolutions or user dependencies as `decision`.
10. After evaluating the criteria, append `complete` when they are satisfied, `failed` when they
    are conclusively unmet and no in-scope recovery remains, or `blocked` when a user or external
    dependency prevents completion or judgment. Otherwise keep the task `active` and return the
    unresolved work to the workflow.

Routine bounded work needs Codex implementation plus Claude verification. Add a fresh reviewer only
for material risk or a distinct unresolved question; do not repeat identical reviews.

## Reference Map

Read only what the current phase needs:

- `references/monitoring.md`: execution capture, CLI monitoring, and handoffs.
- `references/planning.md`: independent planning and plan-review context boundaries.
- `references/review.md`: verification and independent review.
- `references/consensus.md`: consensus and decision outcomes.
- `references/compute.md`: parallel ownership, worktrees, and compute gating.
