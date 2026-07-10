---
name: codex-orchestrator-workflow
description: Run the full Codex orchestration workflow end to end.
---

# Workflow

Use this skill when Claude should run the full Codex orchestration workflow end to end: ledger
setup, planning, dispatch, monitoring, review, verification, consensus, and report.

Use when the user wants one coordinated run that initializes durable state, reuses or resumes
matching Codex agents, dispatches new agents only when needed, monitors their JSONL streams or an
existing IDE thread, reviews the result, records evidence, resolves disagreements, and writes the
final report.

Do not use this skill for a single focused phase such as monitoring, review, consensus, handoff, or
compute gating. Use `${CLAUDE_PLUGIN_ROOT}/skills/orchestrate/SKILL.md` for those. For explicit
ledger-only setup, run the internal CLI init helper and stop.

Default typed protocol workflow:

1. Run `ensure-run` to create or reuse the durable run and record the plugin ref.
2. Append a `task_created` event for each task with a real `goal` plus useful `context` and
   `constraints` string arrays.
3. Run `claim-files` so each task has an explicit `files_allowed` or `file_claimed` allowlist.
4. Run `check-conflicts` before dispatch; resolve overlapping claims before agents edit.
5. Run `render-prompt` so the Codex prompt includes the task goal, context, constraints, and file
   claims.
6. Dispatch Codex for implementation, repair, refactor, or test-writing, reusing a matching session
   when role and context fit.
7. Append `dispatch_started` when the session begins and `dispatch_completed` when it yields,
   completes, or fails.
8. Append `task_checkpoint` with `files_changed` after inspecting the diff and artifacts.
9. Run `add-verification` with `task_id`; it auto-records a verification id and command hash when
   `--command` is present. Use `covers_tasks` and `scope` (`task` or `global`) when evidence covers
   multiple tasks or the whole run. Use `--acceptance-test` for acceptance checks and
   `--finding-id` for repro runs tied to structured review findings.
10. Append a `review` event for the acceptance review. The final-review check accepts only a passing
    `diff` or `manual` review, or a review explicitly marked `final`.
11. Resolve failed checks and blocking findings with basis-bearing `consensus` records. Plain
    agreement clears only command-less convention items; failed executable or acceptance checks need
    linked rerun evidence or an explicit valid override.
12. Run `gate`; it must block missing task-scoped verification, file-claim conflicts, and unclaimed
    changes outside a task allowlist.
13. Run `doctor` to catch ledger, prompt, log, and artifact inconsistencies. Resolve fixable issues
    and rerun gate when the ledger changes.
14. When no further run work is planned, use `${CLAUDE_PLUGIN_ROOT}/skills/report/SKILL.md` to have
    Claude author the complete final report from the ledger, latest `gate_result`, validation output,
    logs, artifacts, and repository diff.

Follow `${CLAUDE_PLUGIN_ROOT}/skills/orchestrate/SKILL.md` for the full operating contract and
concrete procedures.
