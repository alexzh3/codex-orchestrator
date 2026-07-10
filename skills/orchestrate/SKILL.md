---
name: codex-orchestrator-orchestrate
description: Orchestrate, monitor, review, and coordinate Codex agents and IDE sessions from Claude Code.
---

# Claude-Codex Orchestration

Claude is the planner, monitor, reviewer, consensus broker, and compute gate. Codex is the scoped
implementation agent or peer reviewer running in its native IDE or CLI harness.

Default to a Codex-first orchestration pattern for new work: once a usable scope exists, Codex is
the first mover for implementation, repair, refactor, and test-writing. Claude scopes prompts,
reuses matching Codex agents when possible, launches `codex exec --json` only when a new agent is
needed, captures each JSONL stream under the run directory, and monitors the streams with
`${CLAUDE_PLUGIN_ROOT}/scripts/codex_orch_parse.py state` and `tail`.

## When To Use This Skill

Use this skill for focused orchestration phases: dispatch, monitoring, review, consensus, handoff,
or compute gating. Use `${CLAUDE_PLUGIN_ROOT}/skills/workflow/SKILL.md` only for the full end-to-end
run, and `${CLAUDE_PLUGIN_ROOT}/skills/report/SKILL.md` only to author the final `report.md` after
gate and validation from recorded evidence.

This skill is prompt-directed: use the user prompt and recorded run state as scope, and do not create
a full execution plan for focused monitoring, review, consensus, handoff, or compute-gating phases.
Monitoring, review, consensus, handoff, compute gating, and ledger initialization are orchestration
phases, not separate commands.

If the user explicitly asks only to open a ledger, run the internal init helper and stop:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/codex_orch.py" init --repo <repo> --run-id <run-id>
```

## Durable Ledger

Use a durable run ledger for orchestration state:

```text
.codex-orchestrator/runs/<run-id>/
  state.json
  ledger.jsonl
  report.md
  prompts/
  logs/
  artifacts/
```

Keep durable facts in these files, not only in model context. Runtime records follow
`schemas/codex-orchestrator.schema.json`. After gate and doctor complete, Claude authors all of
`report.md` from the final diff, ledger, prompts, logs, artifacts, verification, consensus, and
latest `gate_result`. No Python report renderer fills or rewrites report sections.

Useful helpers:

- `init`: create the run ledger skeleton when a caller explicitly asks only to open a ledger.
- `ensure-run`: create or reuse a run and record the plugin ref before task work starts.
- `status`: inspect compact run state and recent ledger evidence.
- `append-event`: record typed protocol facts such as `task_created`, `dispatch_started`,
  `dispatch_completed`, `task_checkpoint`, `review`, `consensus`, or notes.
- `claim-files`: bind a task to its allowed file set before dispatch.
- `check-conflicts`: detect overlapping task claims before agents edit.
- `render-prompt`: render a task prompt from `task_created.goal`, `context`, `constraints`, and file
  claims.
- `add-verification`: record verification evidence, preferably task-scoped with `task_id`,
  `covers_tasks`, and `scope`.
- `gate`: compute acceptance from verification, final review, file-claim conflicts, and unclaimed
  changes.
- `doctor`: run post-gate consistency checks for the run ledger and artifacts.
- `worktree`: create or inspect isolated worktrees for concurrent scoped agents.
- `benchmark`: run deterministic or configured benchmark suites for the recorded plugin ref.

Use `append-event` only as an advanced escape hatch for custom material facts that do not yet have a
typed command. Known ledger event types are schema-validated; custom event types are recorded as
generic ledger events.

Protocol tasks should carry a real `goal`; optional `context` and `constraints` arrays are rendered
into the Codex prompt by `render-prompt`. Verification can be task-scoped, and the gate matches it to
the requiring task. A passing final-review requirement is satisfied only by a passing `diff` or
`manual` review, or by a review explicitly marked `final`.

Use matching stems for prompts and logs, for example `prompts/final-review.md` and
`logs/final-review.jsonl`. Do this for plan reviews, implementation prompts, diff reviews, consensus
prompts, rereviews, and handoffs, and reference both paths from the relevant ledger record.

## Standard Loop

1. Create or reuse a run id and initialize the ledger if missing.
2. Inspect `state.json` and recent ledger events for existing named Codex agents.
3. For focused phases, use the prompt and recorded run state as scope. If dispatching work and no
   usable scope exists, create only the minimal dispatch plan: task boundary, agent reuse,
   file ownership/isolation, and verification gate.
4. For `/codex-orchestrator:workflow`, have Codex review any new Claude-created plan before
   execution. In focused orchestration, request plan review only when the user asks or risk warrants
   a second opinion.
5. Dispatch or resume Codex for implementation, repair, refactor, or test-writing. Use one reusable
   agent by default, and several only when work can be isolated by worktree, files, or compute.
6. Resume the same relevant Codex session when possible. Start a new session only for unrelated
   work, required isolation, low parser confidence after bounded inspection, or explicit user
   request.
7. Monitor active Codex sessions. Launch monitoring on demand for this phase: arm the native Monitor with the bundled
   `${CLAUDE_PLUGIN_ROOT}/bin/codex-orch-monitor` scoped to the active run, or use the parser recipes
   in `references/monitoring.md`. Do not edit overlapping implementation files while a Codex agent
   owns them; wait until Codex yields, completes, or a serialized handoff is recorded.
8. After Codex yields or completes, review artifacts and run the consensus-gated review loop.
9. Record verification evidence, consensus decisions, and final run state durably.
10. Run `gate`, finish ledger and artifact validation with `doctor`, and only then use the report
    skill to have Claude author the complete final `report.md` for handoff or approval.

## Reference Map

Read the focused references only when that phase is needed:

- `${CLAUDE_PLUGIN_ROOT}/skills/orchestrate/references/monitoring.md`: Codex CLI invocation,
  headless and IDE session monitoring, parser commands, and native Monitor recipes.
- `${CLAUDE_PLUGIN_ROOT}/skills/orchestrate/references/review.md`: diff/test/artifact review,
  independent Codex review, and the review loop.
- `${CLAUDE_PLUGIN_ROOT}/skills/orchestrate/references/consensus.md`: disagreement outcomes,
  required evidence, and ledger/report recording.
- `${CLAUDE_PLUGIN_ROOT}/skills/orchestrate/references/compute.md`: agent identity and reuse,
  multi-session worktrees, handoff, and compute gating.
