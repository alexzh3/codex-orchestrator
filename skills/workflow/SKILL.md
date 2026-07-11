---
name: codex-orchestrator-workflow
description: Run the full Codex orchestration workflow end to end.
---

# Workflow

Use this skill for one complete run: initialize durable context, plan, assign, monitor, review,
verify, decide, close, and report. For a focused phase, use
`${CLAUDE_PLUGIN_ROOT}/skills/orchestrate/SKILL.md` instead.

Follow this sequence:

1. Create `.codex-orchestrator/runs/<run-id>/` and `journal.jsonl`. Append `run_started` with the
   repository, plugin ref, and available Claude/Codex versions.
2. Create active `task` entries with the goal, acceptance criteria, and allowed/owned file paths or
   globs in `files`. Ask Codex to review Claude's plan when a second opinion materially reduces risk.
   For a consequential, ambiguous, or hard-to-reverse design choice, first ask a fresh Codex agent
   for an unanchored alternative before showing it Claude's candidate, then compare them.
3. Check task file ownership before parallel execution. Use sequential work or native Git worktrees
   whenever owned paths overlap.
4. Name each persistent agent `<provider>-<role>-<sequence>`. For prompted work, save the exact
   prompt under `<agent>/execution-NN/prompt.md`. An observe-only attachment to an already active
   IDE session uses `mode: "observe"` and may omit `prompt` because Claude sent none.
5. Append `execution` before launch, then capture the raw event stream and exact handoff. Resume a
   contextually relevant implementation or fix session. An initial independent review or unanchored
   alternative starts a fresh agent and native session as defined in
   `${CLAUDE_PLUGIN_ROOT}/skills/orchestrate/references/review.md`.
6. Monitor each execution until completion, failure, blocking, or staleness. Append Claude's
   terminal `execution_result`; this is durable workflow memory, not mechanical proof, and it does
   not complete the task.
7. Read the handoff as claims. Inspect the actual diff and independently check material behavior.
   Record each criterion evaluation as `verification`, with optional files under `evidence/` only
   when the observation is lengthy, binary, disputed, or important to audit.
8. If Claude and a Codex agent disagree, use a targeted follow-up and record the outcome as a
   `decision`: `consensus`, `claude_decision`, or `user_action_required`.
9. Repeat execution, review, and verification as needed. Append a terminal `task` entry only after
   Claude has evaluated its acceptance criteria.
10. Re-read the full journal, inspect the final repository state and diff, then run the descriptive
    close check:

   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/codex_orch_tools.py" validate \
     .codex-orchestrator/runs/<run-id>
   ```

11. Resolve structural issues, inspect all non-passing checks, and append one final `run_closed`
    entry with `judgment: passed|blocked`, the exact validation result, unresolved risks, and
    follow-ups. Validation detects omissions; Claude decides whether the work is acceptable.
12. Only after `run_closed`, use `${CLAUDE_PLUGIN_ROOT}/skills/report/SKILL.md` to have Claude create
    the final `report.md` once.

Scale review effort to risk. Routine bounded work uses Codex implementation plus Claude
verification. Material localized risk may justify one fresh reviewer; ambiguous or hard-to-reverse
choices may justify an unanchored alternative. Add reviewers only for distinct unresolved
questions.

The canonical close sequence is `validate → run_closed → report.md`. Validation never decides
acceptance, and the final report never repairs or rewrites journal history.

Follow `${CLAUDE_PLUGIN_ROOT}/skills/orchestrate/SKILL.md` for the complete run protocol and
its focused references for monitoring, review, decisions, and compute isolation.
