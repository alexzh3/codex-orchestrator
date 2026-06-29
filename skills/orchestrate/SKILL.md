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
run, and `${CLAUDE_PLUGIN_ROOT}/skills/report/SKILL.md` only to regenerate `report.md` from recorded
evidence.

This skill is prompt-directed: use the user prompt and recorded run state as scope, and do not create
a full execution plan for focused monitoring, review, consensus, handoff, or compute-gating phases.
Monitoring, review, consensus, handoff, compute gating, and ledger initialization are orchestration
phases, not separate slash commands.

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
`schemas/codex-orchestrator.schema.json`. Claude authors the `Summary` and `Changes` sections of
`report.md` after inspecting the diff, ledger, prompts, logs, and verification; the report helper
preserves those sections and regenerates `Evidence`, `Consensus`, and `Risks / Follow-ups`.

Useful helpers:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/codex_orch.py" status --run-id <run-id>
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/codex_orch.py" add-verification --run-id <run-id> --kind test --command "<cmd>" --exit-code <n> --result passed --summary "<summary>"
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/codex_orch.py" append-event --run-id <run-id> '{"type":"note"}'
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/codex_orch.py" report --run-id <run-id>
```

Use `append-event` only as an advanced escape hatch for custom material facts that do not yet have a
typed command. Known ledger event types are schema-validated; custom event types are recorded as
generic ledger events.

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
7. Monitor active Codex sessions. Do not edit overlapping implementation files while a Codex agent
   owns them; wait until Codex yields, completes, or a serialized handoff is recorded.
8. After Codex yields or completes, review artifacts and run the consensus-gated review loop.
9. Record verification evidence, consensus decisions, and final report state durably.
10. Generate or update `report.md` for handoff or approval.

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
