# Orchestration Contract

The run journal preserves Claude's concise causal history and links to supporting material; it
is not a workflow engine, independent evidence, or an automated telemetry source. Claude makes the
semantic judgments. The bundled tools only summarize event streams and check a small set of
structural omissions.

## Record Authority

- **Prompt:** the exact immutable input sent for one execution. It records assigned scope.
- **Event stream:** raw Codex JSONL. It records what the harness emitted and supports lifecycle
  checks, monitoring, or debugging.
- **Handoff:** the exact final agent response. It is a compact package of agent claims.
- **Evidence:** an inspectable observation that supports or contradicts a verification or decision.
- **Verification:** Claude's evaluation of a task criterion using an explicit check and observation.
- **Decision:** Claude's recorded resolution of a consequential disagreement, risk, or user need.
- **Journal:** Claude's compact chronology, current task state, decisions, and links to these sources.
- **Repository:** the final state relative to the recorded starting baseline determines what code
  was actually delivered.

A handoff can establish that an agent *claimed* a test passed, and an event stream can establish
that the harness emitted that claim. Neither establishes that the test passed against the accepted
repository state. Claude independently checks material claims before recording verification.

Evidence need not always be a file. Keep a small command result or diff observation inline. Use the
optional `evidence/` directory for lengthy output, screenshots, metrics, failure diagnostics, or
material that another reviewer may need to inspect later. Do not copy handoffs into `evidence/`.

## Journal Entries

One Claude orchestrator owns and appends to `journal.jsonl`. Every nonblank line is one JSON object
with `recorded_at`. Do not let two orchestration loops write the same run. Duplicate IDs invalidate
the run structure: retain the journal, stop appending, and start a successor run that references the
prior run instead of rewriting history. The journal contains seven entry types. The fields below
are the prompted run protocol, not a complete runtime-enforced schema.

### `run_started`

The first entry. It records the concise original goal, absolute target worktree, starting Git
baseline, plugin revision, and available tool versions. `repo_head` is the full starting commit;
include `repo_branch` only when HEAD is attached. `repo_status` is an array containing the exact
lines from `git status --short --untracked-files=all`, captured after locally excluding the run root
and before creating it.

```jsonl
{"type":"run_started","run_id":"run-20260710-01","goal":"Add request validation without changing the public API.","repo":"/work/project","repo_head":"0123456789abcdef0123456789abcdef01234567","repo_branch":"feature/request-validation","repo_status":[],"plugin_ref":"git:abc1234","claude_version":"2.1.0","codex_version":"0.110.0","recorded_at":"2026-07-10T12:00:00Z"}
```

Omit an unavailable version or detached `repo_branch`; do not guess it. Treat initially dirty paths
as pre-existing user work. If planned work overlaps them, isolate the work or get user direction;
the status alone cannot attribute later edits within the same file.

### `task`

Entries may repeat for the same task. The latest entry is current within the journal. Status is `pending`,
`active`, `complete`, `blocked`, or `failed`. Active tasks declare their allowed/owned file paths or
globs in `files` before parallel execution; parallel tasks must have disjoint ownership or use
isolated worktrees. This planned boundary is distinct from `execution_result.files_changed`, which
is Claude's compact attribution note; the repository diff determines what actually changed.

```jsonl
{"type":"task","id":"task-01","status":"active","goal":"Add request validation.","acceptance":["Invalid input is rejected","Relevant tests pass"],"files":["src/api.py","tests/test_api.py"],"recorded_at":"2026-07-10T12:01:00Z"}
```

### `execution`

Append this before launch so in-flight work survives context loss. The `agent` + `execution` pair is
its identity. Record the absolute `worktree`, full Git `head`, and attached `branch` when present so
resume and integration use the same target after context loss. Record the provider, role, and mode.
Use `event_source: "exec"` for a Codex CLI stream and `"claude"` for a Claude agent. `events` may be
omitted for a Claude agent. Record `model`, `effort`, and `session_id` when known; an execution
result may supply the session id later.

```jsonl
{"type":"execution","agent":"codex-impl-01","execution":"execution-01","task":"task-01","provider":"codex","role":"implementation","mode":"headless","event_source":"exec","model":"gpt-5","effort":"high","worktree":"/work/project-codex-impl-01","head":"0123456789abcdef0123456789abcdef01234567","branch":"codex-impl-01","prompt":"codex-impl-01/execution-01/prompt.md","events":"codex-impl-01/execution-01/events.jsonl","handoff":"codex-impl-01/execution-01/handoff.md","recorded_at":"2026-07-10T12:02:00Z"}
```

### `execution_result`

Records Claude's terminal understanding of one execution as `complete`, `blocked`, or `failed`. It
links the exact handoff and summarizes reported or observed files, results, and caveats. It is not
mechanical process telemetry or authoritative file attribution; a complete execution result does
not complete the task.

```jsonl
{"type":"execution_result","agent":"codex-impl-01","execution":"execution-01","task":"task-01","status":"complete","session_id":"thread-123","handoff":"codex-impl-01/execution-01/handoff.md","summary":"Implemented validation and tests.","files_changed":["src/api.py","tests/test_api.py"],"caveats":[],"recorded_at":"2026-07-10T12:20:00Z"}
```

An execution is in flight until a matching terminal execution result exists. Completed executions
require a nonempty handoff. A missing handoff for a blocked or failed execution is reported as a
warning and must not be fabricated.

### `verification`

Records Claude's evaluation of one criterion. Result is `passed`, `failed`, `inconclusive`, or
`skipped`. The `check` is the exact command or inspection, and `observation` states what Claude
actually observed. Evidence paths are optional.

```jsonl
{"type":"verification","id":"check-01","task":"task-01","criterion":"Relevant tests pass","method":"command","check":"python -m pytest tests/test_api.py -q","result":"passed","observation":"12 tests passed; exit code 0.","evidence":["evidence/task-01-tests.txt"],"recorded_at":"2026-07-10T12:25:00Z"}
```

The agent's `Commands Reported` section is not a verification. Claude must observe the check or
perform an inspection appropriate to the criterion.

### `decision`

Records a consequential resolution. Outcome is `consensus`, `claude_decision`, or
`user_action_required`. `basis` references checks, handoffs, evidence, or repository paths; `risk`
states residual risk. Decisions explain history but do not delete or rewrite failed checks.

```jsonl
{"type":"decision","id":"decision-01","task":"task-01","finding":"The first implementation accepted whitespace-only names.","outcome":"consensus","resolution":"Reject stripped empty names and retain the regression test.","basis":["check-01","codex-impl-01/execution-02/handoff.md"],"risk":"low","recorded_at":"2026-07-10T12:45:00Z"}
```

### `run_closed`

The final journal entry. Claude copies the pre-close validation result into `validation` and records
the semantic `judgment` as `passed` or `blocked`, plus unresolved risks and follow-ups.

```jsonl
{"type":"run_closed","judgment":"passed","summary":"All acceptance criteria were independently verified.","validation":{"ok":true,"issues":[],"warnings":[],"non_passing_verifications":[]},"risks":[],"follow_ups":[],"recorded_at":"2026-07-10T13:00:00Z"}
```

The `validation` field preserves the descriptive check immediately preceding closure. Validation
does not decide `judgment`: Claude reviews its output, all non-passing verification, open decisions,
and repository state before closing the run. The workflow skill owns the complete close procedure.

## Handoff Contract

Every agent prompt asks for a concise final response with these headings:

```markdown
## Status

## Summary

## Files Changed

## Claims / Findings

## Commands Reported

## Caveats / Blockers
```

Codex writes this exact response with `--output-last-message`. Claude agents save the exact returned
message locally. Do not rewrite a handoff into a cleaner summary; add Claude's observations to the
execution result or verification instead.

## Failed Checks And Reruns

Keep both observations. A passing rerun supports acceptance of the corrected repository state but
does not erase the earlier failure. Record the failed verification, fix execution, and passing
verification.

[`tests/replay/long-run-001/`](../tests/replay/long-run-001/) is a checked-in input scaffold, not a
standalone valid closed run. [`test_prompt_first_workflow.py`](../tests/test_prompt_first_workflow.py)
copies it, generates the fake execution outputs, evidence, and example repository files, then
validates the completed copy.

## Descriptive Validation

`validate` is a small omission check, not truth or acceptance validation. It checks:

- JSON objects and the seven journal entry type names;
- one initial `run_started` and at most one final `run_closed`;
- execution/result identities, pairing, order, and matching task IDs when recorded;
- task references plus duplicate verification and decision IDs;
- declared prompt, event, handoff, and evidence files;
- terminal execution results and latest task states before closure;
- nonempty completed-execution handoffs;
- recognized verification results and a descriptive list of every non-passing verification.

Its output is ordinary JSON, not a journal entry:

```json
{
  "ok": true,
  "issues": [],
  "warnings": [],
  "non_passing_verifications": []
}
```

Validation does not enforce every documented field, confine paths, resolve decision bases, match
reruns, clear failures, infer consensus, verify process provenance, or decide acceptance. Claude
copies the complete result into `run_closed.validation`, then authors `report.md` from the complete
run context.
