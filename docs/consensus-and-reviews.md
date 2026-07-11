# Claims, Evidence, Verification, And Decisions

The runtime ledger preserves Claude's concise causal journal and links to supporting material; it
is not a workflow engine, independent evidence, or an automated telemetry source. Claude makes the
semantic judgments. The parser and validator only summarize event streams and check a small set of
structural omissions.

## Trust Boundaries

- **Prompt:** the exact immutable input sent for one execution. It records assigned scope.
- **Event stream:** raw Codex JSONL, or an external IDE rollout. It records what the harness emitted
  and supports lifecycle checks, monitoring, or debugging.
- **Handoff:** the exact final agent response. It is a compact package of agent claims.
- **Evidence:** an inspectable observation that supports or contradicts a verification or decision.
- **Verification:** Claude's evaluation of a task criterion using an explicit check and observation.
- **Decision:** Claude's recorded resolution of a consequential disagreement, risk, or user need.
- **Ledger:** Claude's compact chronology, current task state, decisions, and links to these sources.
- **Repository:** the final state and diff that determine what code was actually delivered.

A handoff can establish that an agent *claimed* a test passed, and an event stream can establish
that the harness emitted that claim. Neither establishes that the test passed against the accepted
repository state. Claude independently checks material claims before recording verification.

Evidence need not always be a file. Keep a small command result or diff observation inline. Use the
optional `evidence/` directory for lengthy output, screenshots, metrics, failure diagnostics, or
material that another reviewer may need to inspect later. Do not copy handoffs into `evidence/`.

## Run Layout

```text
.codex-orchestrator/runs/<run-id>/
  ledger.jsonl
  agents/
    codex-impl-01/
      execution-01/
        prompt.md
        events.jsonl
        handoff.md
  evidence/
  report.md
```

Agent names use `<provider>-<primary-role>-<sequence>`. Each prompt/execution/handoff cycle gets the
next `execution-NN` directory directly under that agent. A resumed Codex session remains the same
agent and gets a new execution; a deliberately fresh session gets a new agent name.

For IDE sessions, `execution.events` is an absolute rollout path and is not copied into the run.
Attaching only to observe an already-active IDE session uses `mode: "observe"` and may omit `prompt`
because Claude sent nothing. A later follow-up is a new, normal prompted execution. Claude agent
executions may omit `events` when no raw stream is exposed. Never fabricate one.

## Ledger Vocabulary

Only Claude, acting as orchestrator, appends to `ledger.jsonl`. Every nonblank line is one JSON
object with `recorded_at`. The vocabulary contains seven event types. The fields below are the
prompted journal contract, not a complete runtime-enforced schema.

### `run_started`

The first record. It identifies the run, repository, plugin revision, and available tool versions.

```jsonl
{"type":"run_started","run_id":"run-20260710-01","repo":"/work/project","plugin_ref":"git:abc1234","claude_version":"2.1.0","codex_version":"0.110.0","recorded_at":"2026-07-10T12:00:00Z"}
```

Omit a version when unavailable; do not guess it.

### `task`

Records may repeat for the same task. The latest record is current within the journal. Status is `pending`,
`active`, `complete`, `blocked`, or `failed`. Active tasks declare their allowed/owned file paths or
globs in `files` before parallel execution; parallel tasks must have disjoint ownership or use
isolated worktrees. This planned boundary is distinct from `execution_result.files_changed`, which
is Claude's compact attribution note; the repository diff determines what actually changed.

```jsonl
{"type":"task","id":"task-01","status":"active","goal":"Add request validation.","acceptance":["Invalid input is rejected","Relevant tests pass"],"files":["src/api.py","tests/test_api.py"],"recorded_at":"2026-07-10T12:01:00Z"}
```

### `execution`

Append this before launch so in-flight work survives context loss. The `agent` + `execution` pair is
its identity. Record the provider, role, and mode. Use `event_source: "exec"` for a headless Codex
stream, `"ide"` for an external rollout, and `"claude"` for a Claude agent. `events` may be omitted
for a Claude agent. Record `model`, `effort`, and `session_id` when known; an execution result may
supply the session id later.

```jsonl
{"type":"execution","agent":"codex-impl-01","execution":"execution-01","task":"task-01","provider":"codex","role":"implementation","mode":"headless","event_source":"exec","model":"gpt-5","effort":"high","prompt":"agents/codex-impl-01/execution-01/prompt.md","events":"agents/codex-impl-01/execution-01/events.jsonl","handoff":"agents/codex-impl-01/execution-01/handoff.md","recorded_at":"2026-07-10T12:02:00Z"}
```

Observe-only IDE attachment has no prompt because Claude provided no execution input:

```jsonl
{"type":"execution","agent":"codex-observe-01","execution":"execution-01","task":"task-01","provider":"codex","role":"monitoring","mode":"observe","event_source":"ide","session_id":"thread-123","events":"/home/user/.codex/sessions/2026/07/10/rollout-thread-123.jsonl","handoff":"agents/codex-observe-01/execution-01/handoff.md","recorded_at":"2026-07-10T12:02:00Z"}
```

### `execution_result`

Records Claude's terminal understanding of one execution as `complete`, `blocked`, or `failed`. It
links the exact handoff and summarizes reported or observed files, results, and caveats. It is not
mechanical process telemetry or authoritative file attribution; a complete execution result does
not complete the task.

```jsonl
{"type":"execution_result","agent":"codex-impl-01","execution":"execution-01","task":"task-01","status":"complete","session_id":"thread-123","handoff":"agents/codex-impl-01/execution-01/handoff.md","summary":"Implemented validation and tests.","files_changed":["src/api.py","tests/test_api.py"],"caveats":[],"recorded_at":"2026-07-10T12:20:00Z"}
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
{"type":"decision","id":"decision-01","task":"task-01","finding":"The first implementation accepted whitespace-only names.","outcome":"consensus","resolution":"Reject stripped empty names and retain the regression test.","basis":["check-01","agents/codex-impl-01/execution-02/handoff.md"],"risk":"low","recorded_at":"2026-07-10T12:45:00Z"}
```

### `run_closed`

The final ledger record. Claude copies the pre-close validation result into `validation` and records
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

Headless Codex writes this exact response with `--output-last-message`. IDE and Claude agents save
the exact returned message locally. Do not rewrite a handoff into a cleaner summary; add Claude's
observations to the execution result or verification instead.

## Failed Check, Fix, And Rerun

Keep both observations. A passing rerun supports acceptance of the new repository state, but it does
not make the earlier failure disappear. This complete example shows the lifecycle from run start to
closure:

```jsonl
{"type":"run_started","run_id":"run-20260710-01","repo":"/work/project","plugin_ref":"git:abc1234","claude_version":"2.1.0","codex_version":"0.110.0","recorded_at":"2026-07-10T12:00:00Z"}
{"type":"task","id":"task-01","status":"active","goal":"Add request validation.","acceptance":["Invalid input is rejected","Relevant tests pass"],"files":["src/api.py","tests/test_api.py"],"recorded_at":"2026-07-10T12:01:00Z"}
{"type":"execution","agent":"codex-impl-01","execution":"execution-01","task":"task-01","provider":"codex","role":"implementation","mode":"headless","event_source":"exec","model":"gpt-5","effort":"high","prompt":"agents/codex-impl-01/execution-01/prompt.md","events":"agents/codex-impl-01/execution-01/events.jsonl","handoff":"agents/codex-impl-01/execution-01/handoff.md","recorded_at":"2026-07-10T12:02:00Z"}
{"type":"execution_result","agent":"codex-impl-01","execution":"execution-01","task":"task-01","status":"complete","session_id":"thread-123","handoff":"agents/codex-impl-01/execution-01/handoff.md","summary":"Implemented validation and tests.","files_changed":["src/api.py","tests/test_api.py"],"caveats":[],"recorded_at":"2026-07-10T12:20:00Z"}
{"type":"verification","id":"check-01","task":"task-01","criterion":"Whitespace-only names are rejected","method":"command","check":"python -m pytest tests/test_api.py -q","result":"failed","observation":"1 failed, 11 passed; whitespace-only input was accepted.","recorded_at":"2026-07-10T12:25:00Z"}
{"type":"execution","agent":"codex-impl-01","execution":"execution-02","task":"task-01","provider":"codex","role":"fix","mode":"headless","event_source":"exec","session_id":"thread-123","prompt":"agents/codex-impl-01/execution-02/prompt.md","events":"agents/codex-impl-01/execution-02/events.jsonl","handoff":"agents/codex-impl-01/execution-02/handoff.md","recorded_at":"2026-07-10T12:27:00Z"}
{"type":"execution_result","agent":"codex-impl-01","execution":"execution-02","task":"task-01","status":"complete","session_id":"thread-123","handoff":"agents/codex-impl-01/execution-02/handoff.md","summary":"Added stripped-empty validation and regression coverage.","files_changed":["src/api.py","tests/test_api.py"],"caveats":[],"recorded_at":"2026-07-10T12:40:00Z"}
{"type":"verification","id":"check-02","task":"task-01","criterion":"Whitespace-only names are rejected","method":"command","check":"python -m pytest tests/test_api.py -q","result":"passed","observation":"12 tests passed; exit code 0.","evidence":["evidence/task-01-tests-after-fix.txt"],"recorded_at":"2026-07-10T12:43:00Z"}
{"type":"decision","id":"decision-01","task":"task-01","finding":"The first implementation accepted whitespace-only names.","outcome":"consensus","resolution":"The defect was fixed and the same test command passed against the corrected worktree.","basis":["check-01","check-02"],"risk":"low","recorded_at":"2026-07-10T12:45:00Z"}
{"type":"task","id":"task-01","status":"complete","goal":"Add request validation.","acceptance":["Invalid input is rejected","Relevant tests pass"],"files":["src/api.py","tests/test_api.py"],"summary":"Validation and regression coverage accepted after fix and rerun.","recorded_at":"2026-07-10T12:46:00Z"}
{"type":"run_closed","judgment":"passed","summary":"The task passed after the defect was fixed and independently rerun.","validation":{"ok":true,"issues":[],"warnings":[],"non_passing_verifications":[{"id":"check-01","task":"task-01","result":"failed","check":"python -m pytest tests/test_api.py -q","observation":"1 failed, 11 passed; whitespace-only input was accepted."}]},"risks":[],"follow_ups":[],"recorded_at":"2026-07-10T13:00:00Z"}
```

Use `claude_decision` when Claude proceeds despite remaining model disagreement; record the rejected
alternative, rationale, and residual risk. Use `user_action_required` when progress or acceptance
needs authority or information Claude does not have. Unresolved required user action normally
produces `run_closed.judgment: blocked`.

## Descriptive Validation

`validate` is a small omission check, not truth or acceptance validation. It checks:

- JSON objects and the seven event names;
- one initial `run_started` and at most one final `run_closed`;
- execution/result identities, pairing, order, and matching task IDs when recorded;
- task references plus duplicate verification and decision IDs;
- declared prompt, event, handoff, and evidence files;
- terminal execution results and latest task states before closure;
- nonempty completed-execution handoffs;
- recognized verification results and a descriptive list of every non-passing verification.

Its output is ordinary JSON, not a ledger event:

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
