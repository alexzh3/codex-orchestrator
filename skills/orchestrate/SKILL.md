---
name: codex-orchestrator-orchestrate
description: Orchestrate, monitor, review, and coordinate Codex agents and IDE sessions from Claude Code.
---

# Claude-Codex Orchestration

Claude is the planner, orchestrator, monitor, and final reviewer. Codex is a scoped implementer or
peer reviewer running in its native CLI or IDE harness. Prefer Codex as the first mover for bounded
implementation, repair, refactor, test-writing, and independent review work.

Use this skill for a focused orchestration phase. Use
`${CLAUDE_PLUGIN_ROOT}/skills/workflow/SKILL.md` for a complete run and
`${CLAUDE_PLUGIN_ROOT}/skills/report/SKILL.md` only after the run has closed.

## Run Protocol

Keep durable run material under:

```text
.codex-orchestrator/runs/<run-id>/
  journal.jsonl
  agents/
    codex-impl-01/
      execution-01/
        prompt.md
        events.jsonl
        handoff.md
  evidence/                 # optional; create only when needed
  report.md                 # authored by Claude after run_closed
```

Agent names use `<provider>-<primary-role>-<sequence>`, for example `codex-impl-01`,
`codex-review-01`, or `claude-review-01`. A persistent agent may have several numbered executions.
Resume a relevant implementation, fix, or targeted-recheck session under the same agent directory.
Start a fresh named agent and native session for an initial independent review or unanchored
alternative; otherwise create one only for unrelated work, required isolation, an unusable session,
or an explicit request for a fresh one.

Each prompted execution directory contains:

- `prompt.md`: the exact immutable input sent for that execution.
- `events.jsonl`: the raw Codex event stream used for monitoring and debugging.
- `handoff.md`: the exact final agent response, captured directly when possible.

An observe-only IDE attachment omits `prompt.md` because Claude sent no prompt. IDE executions may
reference an absolute external rollout path instead of copying an event stream. Claude agents may
omit `events` when their harness exposes no raw stream. Never synthesize a log.

## Trust Boundaries

Prompts define assigned scope. Handoffs record agent claims. Event streams show what the harness
emitted. The journal records Claude's chronology, task state, and decisions. Evidence is an
inspectable observation used to verify those claims against checks and the final repository state.
Keep small observations inline; put lengthy output, screenshots, or metrics under `evidence/`.

## Run Journal

`journal.jsonl` is Claude's concise append-only orchestration journal and navigation index. Each
journal entry is one compact JSON object with `recorded_at`. Use exactly these entry types:

- `run_started`: first entry; run id, repository, plugin ref, and available Claude/Codex versions.
- `task`: goal, acceptance criteria, allowed/owned file paths or globs in `files`, and latest task
  status.
- `execution`: written before launch with `agent`, `execution`, `task`, provider, role, mode, event
  source, paths, and the model, effort, and `session_id` when known.
- `execution_result`: Claude's recorded terminal outcome for one execution: `complete`, `blocked`,
  or `failed`.
- `verification`: Claude's evaluation of a criterion using an explicit check and observation.
- `decision`: a consequential resolution with outcome, basis, and risk.
- `run_closed`: the final entry, including `judgment: passed|blocked`, validation result, risks, and
  follow-ups.

A task entry may be repeated; its latest entry is current within the journal. An execution is in
flight until Claude records a matching terminal execution result. A complete execution result does
not complete its task: keep the task active until Claude has inspected the work, verified material
claims, and recorded any needed decision. See
`${CLAUDE_PLUGIN_ROOT}/docs/orchestration-contract.md` for the recommended fields and worked
example.

## Standard Loop

1. Create the run directory and append `run_started` before task work.
2. Append active `task` entries with concrete goals, acceptance criteria, and allowed/owned file
   paths or globs in `files`.
3. Before parallel work, verify that task-owned file lists are disjoint. Serialize overlapping work
   or use native Git worktrees.
4. Choose a relevant existing agent or create a named agent. Save the exact prompt under its next
   `execution-NN` directory. When only attaching to an already-active IDE session, use
   `mode: "observe"`; no prompt path is required because Claude sent no prompt.
5. Append `execution` before assigning work to the agent. This makes in-flight work recoverable after
   context loss.
6. Monitor the event stream with the bundled session tools. Do not edit files concurrently with an
   agent that owns them.
7. Save the exact final response as `handoff.md`, inspect it and the repository, then append a
   terminal `execution_result` with Claude's concise outcome, observed or reported files, and
   caveats. The final repository state determines what was actually delivered.
8. Independently verify material claims. Record checks as `verification`; create evidence files only
   when inline observations are insufficient.
9. Record consequential agreements, disagreements, overrides, or user dependencies as `decision`.
10. Append a terminal `task` entry after its acceptance criteria have been evaluated.
11. When no work remains, use the workflow skill's close procedure, then invoke the report skill.

The workflow's validation step is a small descriptive omission check: it checks readable entries,
lifecycle pairing, declared files, terminal task state, and visible non-passing checks. It is not a
complete journal-entry schema and does not validate decision rationale or implementation truth. Claude
makes the final judgment; do not treat descriptive validation as semantic acceptance.

## Reference Map

Read only the references needed for the current phase:

- `references/monitoring.md`: execution capture, CLI and IDE monitoring, tool commands, handoffs.
- `references/review.md`: claims, independent evidence, verification, and review loops.
- `references/consensus.md`: decision outcomes and disagreement handling.
- `references/compute.md`: parallel ownership, worktrees, and compute gating.
