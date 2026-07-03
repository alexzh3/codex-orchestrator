# Consensus And Reviews

This document explains how the 0.3.6 evidence flow works. It is for maintainers who need to read a
ledger, understand why `gate` passed or blocked, and know what `doctor` is warning about.

## The Flow At A Glance

```
task_created + file claims
  -> Codex implementation
  -> verification events for concrete checks
  -> review events for human/agent judgment
  -> consensus events for resolved failures or disagreements
  -> gate decides ship/no-ship from the ledger
  -> doctor audits ledger integrity
  -> report renders the run for humans
```

The ledger is the source of truth. Tasks define work and file ownership. Codex implements and records
checkpoints. Verifications record command runs such as tests, lint, build, typecheck, benchmarks, and
manual review checks. Reviews record human or agent judgment, including structured blocking findings
when a review claims something is still wrong. Consensus records explain how a failed check,
blocking finding, or disagreement was resolved. `gate` reads the ledger and decides whether the run
can be accepted. `doctor` is read-only and reports integrity problems. `report` renders the ledger
for maintainers.

## Verification Events

A verification records one piece of evidence. Example:

```json
{
  "type": "verification",
  "id": "V1",
  "kind": "test",
  "result": "failed",
  "summary": "Unit tests failed before the fix.",
  "command": "python3 -m unittest discover -s tests -v",
  "command_hash": "sha256:a66b8f178d020ef6bfbcc8acf88c601828ddceb38cdd22c61aef2bdb2aa0d57c",
  "task_id": "T001",
  "acceptance_test": true,
  "attempt_count": 1,
  "stochastic": false,
  "exit_code": 1,
  "artifacts": ["logs/unit-tests.txt"]
}
```

Fields:

- `kind`: the check category, such as `test`, `lint`, `build`, `typecheck`, `benchmark`,
  `artifact_check`, `screenshot`, `manual_review`, `git_diff`, or `custom`.
- `result`: `passed`, `failed`, `skipped`, `inconclusive`, or `needs_human_review`. Gate treats
  `failed`, `inconclusive`, and `needs_human_review` as unresolved unless a later consensus clears
  them with a valid evidence basis.
- `summary`: human-readable explanation of what happened.
- `command`: the exact command string that was run. Gate rerun checks compare this exact command
  after only CRLF normalization and outer whitespace stripping through the shared command hash.
- `command_hash`: audit metadata computed as `sha256:` plus the hash of the normalized command.
  Gate always recomputes from `command`; it never trusts a stored hash. If a stored hash disagrees
  with `command`, `doctor` emits `command-hash-mismatch`.
- `id`: a non-empty verification identifier such as `V1`. `add-verification` auto-generates the
  first unused `Vn`; explicit duplicate ids are rejected by the CLI. Consensus refs use
  `verification:<id>`.
- `task_id`, `covers_tasks`, `scope`: limit or broaden which task a verification satisfies.
  Unscoped verifications can satisfy any task requirement; `scope: "global"` covers the run.
- `acceptance_test`: marks the verification as an acceptance check. Failed acceptance checks cannot
  be cleared by `accepted_risk`, `non_executable_convention`, or `user_override` in 0.3.6. A later
  passing rerun can clear one only when both records have the same non-empty command, kind, task,
  and acceptance flag.
- `attempt_count`: number of attempts represented by this record. Missing or invalid values count
  as 1 in gate logic.
- `stochastic`: when true, `repro_not_reproduced` requires at least 3 passing rerun attempts.
- `exit_code`: process exit code when there was one.
- `artifacts`: paths or artifact names that support the verification.
- `finding_id`: links a repro run to a structured review finding. For findings, gate only counts
  a verification as repro evidence when it has the same `finding_id`, appears later in the ledger
  than the review that filed the finding, and ran the finding's exact `repro_command`.

## CLI Flags

`add-verification` appends a validated verification event.

| Flag | Meaning |
| --- | --- |
| `--repo` | Repository root. Defaults to `.`. |
| `--run-id` | Run id under `.codex-orchestrator/runs/`. |
| `--kind` | Verification kind. Required. |
| `--result` | Verification result. Required. |
| `--summary` | Non-empty summary. Required. |
| `--id` | Optional explicit id. Duplicate existing ids are rejected. |
| `--command` | Exact command string. When present, the CLI also records `command_hash`. |
| `--exit-code` | Integer process exit code. |
| `--artifact` | Repeatable artifact path or name. |
| `--notes` | Optional notes. |
| `--task-id` | Task this verification primarily covers. |
| `--finding-id` | Review finding this verification reproduces or disproves. |
| `--acceptance-test` | Marks the verification as an acceptance check. |
| `--attempt-count` | Positive integer attempt count. `0`, negatives, and non-integers fail argparse. |
| `--covers-tasks` | Repeatable extra task ids this verification covers. |
| `--scope` | `task` or `global`. |

`gate` appends a `gate_result` and exits nonzero when blocking reasons exist. `doctor` performs
read-only integrity checks and never mutates the ledger. `report --strict` renders `report.md` and
fails when required report sections still contain missing-evidence placeholders; 0.3.6 did not
change strict-report scoring or placeholders.

## Review Events And Blocking Findings

A typed review records a review result. It may include legacy free-form `findings` and structured
`blocking_findings`.

```json
{
  "type": "review",
  "task_id": "T001",
  "reviewer": "claude",
  "kind": "diff",
  "result": "failed",
  "summary": "The patch still has a runtime issue.",
  "blocking_findings": [
    {
      "id": "F1",
      "claim": "The migration can silently drop records.",
      "severity": "P1",
      "repro_command": "python3 -m unittest tests.test_migrations -v",
      "min_repro_attempts": 3
    }
  ]
}
```

Structured finding fields:

- `id`: non-empty finding id, referenced as `finding:<id>`.
- `claim`: the concrete claim being made.
- `severity`: `P0`, `P1`, or `P2`; default is `P1`.
- `file_refs`: optional file references.
- `repro_command`: exact command a later verification must run to count as repro evidence.
- `min_repro_attempts`: positive integer required passing attempts; default is 1.

Finding lifecycle:

1. A review files a P0 or P1 finding with `repro_command`.
2. Until later valid repro evidence or a later `accepted_risk`/`user_override` consensus clears the
   finding by `finding:<id>`, `gate` emits `pending-repro`.
3. A later verification with matching `finding_id` and exact `repro_command` counts as repro
   evidence. If that verification failed, it blocks as `unresolved-verification`; gate avoids
   double-counting it as `pending-repro`.
4. Enough later passing repro attempts satisfy the finding, so it no longer blocks.
5. P2 findings never block. P0/P1 findings without `repro_command` do not block, but gate emits a
   `finding-no-repro-command` warning and `doctor` emits `finding-missing-repro`.
6. A later review can re-file the same finding id. Gate evaluates each occurrence independently;
   an earlier clear does not clear a later re-file.

## Consensus Events

Consensus records explain how failed evidence, findings, or disagreements were resolved.

```json
{
  "type": "consensus",
  "finding": "Unit tests failed.",
  "outcome": "consensus",
  "resolution": "The same command passed on a later rerun.",
  "resolution_basis": "rerun_passed",
  "evidence": ["rerun output"],
  "clears": ["verification:V1"],
  "evidence_refs": ["verification:V2"],
  "requires_user": false
}
```

`outcome` is one of:

- `consensus`: Claude and Codex agree after inspecting evidence.
- `claude_decision`: Claude proceeds with recorded rationale.
- `user_action_required`: human input is required. This never resolves a gate blocker.

`requires_user: true` also prevents the consensus from clearing anything, even if `outcome` is
otherwise resolving.

Resolution bases:

| Basis | Meaning | Use when | Can clear |
| --- | --- | --- | --- |
| `rerun_passed` | The same check passed later. | A failed executable check was rerun. | Failed executable or acceptance checks only with a valid rerun link. |
| `repro_not_reproduced` | A stochastic failure did not reproduce. | A flaky check was rerun enough times. | Same as `rerun_passed`, but stochastic checks need 3 passing attempts. |
| `accepted_risk` | A known non-executable risk is accepted. | The issue is a convention, documentation, or policy risk. | Command-less non-acceptance verification failures and findings by `finding:<id>`. |
| `non_executable_convention` | Legacy/default basis for command-less convention decisions. | Old ledgers or convention-only failures. | Command-less non-acceptance verification failures. |
| `user_override` | Explicit human override. | A human explicitly accepts the outcome. | Executable non-acceptance verification failures and findings. It cannot clear acceptance tests in 0.3.6. |

`clears` says what the consensus resolves. It is ref-addressed, and a consensus with a non-empty
`clears` list never falls back to text matching. `evidence_refs` points to proof records; it never
addresses a verification by itself. Both fields use `verification:<id>` and `finding:<id>` refs.

Legacy consensus records without `resolution_basis` default to `non_executable_convention` for gate
logic. That preserves old behavior only for command-less, non-acceptance convention items.

## The Clear Matrix

Verification clearability:

| Verification failure | `rerun_passed` | `repro_not_reproduced` | `accepted_risk` | `non_executable_convention` | `user_override` |
| --- | --- | --- | --- | --- | --- |
| Executable command, not acceptance | Clears with valid rerun | Clears with valid rerun and enough attempts | Blocks | Blocks | Clears |
| Acceptance test with command | Clears with valid rerun | Clears with valid rerun and enough attempts | Blocks | Blocks | Blocks |
| Command-less, not acceptance | Blocks | Blocks | Clears | Clears | Clears |
| Command-less acceptance test | Blocks | Blocks | Blocks | Blocks | Blocks |

Valid rerun links require all of:

- the linked verification result is `passed`;
- the linked verification is recorded earlier in the ledger than the consensus that cites it;
- linked verification `recorded_at` is parseable and strictly newer than the failed verification;
- same `task_id`, treating missing as an empty string;
- same `kind`;
- both records have a non-empty `command`;
- `computed_command_hash(link.command) == computed_command_hash(failed.command)`;
- same `acceptance_test` truth value;
- linked verification id resolves to exactly one record, not a duplicate;
- linked `attempt_count` meets the basis minimum.

## Gate Blocking Reasons And Doctor Checks

Gate blocking prefixes:

- `malformed-ledger`: a ledger line is not valid JSON.
- `missing-report`: `report.md` does not exist.
- `stale-report`: `report.md` is older than the latest non-gate ledger event.
- `file-claim-conflict`: active file claims overlap.
- `unclaimed-change`: a completed task changed a path outside its allowlist.
- `active-task`: a task is not in a terminal status.
- `missing-checkpoint`: a completed task has no `task_checkpoint`.
- `unmet-verification`: a completed task has an unsatisfied `verification_required` entry.
- `unresolved-verification`: a failed, inconclusive, or human-review verification lacks a later
  valid resolving consensus.
- `pending-repro`: a P0/P1 blocking finding still lacks enough later passing repro evidence.
- `unresolved-consensus`: a consensus still requires user action.
- `missing-final-review`: no passing run-wide final review is recorded.

Gate warning prefixes:

- `low-parser-confidence`: a monitored session has low parser confidence.
- `finding-no-repro-command`: a P0/P1 blocking finding lacks `repro_command`; it cannot block.

Doctor prefixes:

- `malformed-ledger`: a ledger line is not valid JSON.
- `invalid-event`: a typed event fails runtime validation.
- `unknown-event`: an unknown non-legacy event type appears.
- `dispatch-missing-paths`: a dispatch record is missing `prompt_path` or `log_path`.
- `malformed-ref`: a consensus ref is not `verification:<id>` or `finding:<id>`.
- `dangling-ref`: a consensus references an unknown verification or finding id.
- `invalid-rerun-link`: a rerun-basis consensus has no valid passing rerun link.
- `ineffective-clear`: a basis cannot clear the verification it targets.
- `duplicate-verification-id`: a verification id appears more than once.
- `duplicate-finding-id`: a blocking finding id appears more than once.
- `command-hash-mismatch`: stored `command_hash` disagrees with the command.
- `finding-missing-repro`: a blocking finding has no `repro_command`.
- `missing-checkpoint`: a task has no checkpoint.
- `missing-verification`: a completed task has no verification or review evidence.
- `accepted-run-unresolved-check`: an accepted run still has unresolved verification evidence.
- `missing-report`: `report.md` does not exist.
- `stale-report`: `report.md` is older than the latest non-gate ledger event.

## Worked Examples

### A Failed Test Cleared By A Rerun

1. Record failed verification `V1` with `command: "python3 -m unittest discover -s tests -v"`.
2. Rerun the exact command and record passing verification `V2` later in the ledger.
3. Add consensus:

```json
{
  "type": "consensus",
  "finding": "Unit tests failed.",
  "outcome": "consensus",
  "resolution": "The same test command passed on rerun.",
  "resolution_basis": "rerun_passed",
  "evidence": ["rerun output"],
  "clears": ["verification:V1"],
  "evidence_refs": ["verification:V2"]
}
```

Gate passes this part only if `V2` was already recorded before the consensus, is passed, strictly
newer, same kind, same task, same command hash, same acceptance flag, and the id is not duplicated.

### Accepted Risk Over A Style Convention

A manual review verification `V1` fails without a command and is not an acceptance test. Consensus
can clear it with:

```json
{
  "type": "consensus",
  "finding": "Style convention differs from preference.",
  "outcome": "consensus",
  "resolution": "Accepted as a documented convention risk.",
  "resolution_basis": "accepted_risk",
  "evidence": ["maintainer reviewed"],
  "clears": ["verification:V1"]
}
```

This would not clear a failed test command or an acceptance check.

### Blocked Plain Agreement Over A Failed Executable Test

A failed test verification has a command. A later consensus with matching text but no basis, clears
ref, or rerun evidence does not clear it in 0.3.6. Gate emits `unresolved-verification`.

### Finding Not Reproduced In Three Attempts

A review files `F1` as P1 with `repro_command`. Later, three passing verifications with
`finding_id: "F1"` run that exact command after the review. Once their total `attempt_count` reaches
the finding's `min_repro_attempts`, the finding stops blocking. If maintainers decide the issue is
accepted risk instead, a later consensus with `resolution_basis: "accepted_risk"` and
`clears: ["finding:F1"]` also clears the finding by explicit ref.

## What Changed In 0.3.6 And Why

Before 0.3.6, matching agreement text could clear failed evidence too easily. That is unsafe for an
ensemble workflow because models can converge on the same plausible but wrong answer. 0.3.6 makes
resolution basis explicit and machine-checkable:

- failed executable or acceptance verifications need a valid linked passing rerun, or an explicit
  `user_override` for non-acceptance checks;
- `accepted_risk` and `non_executable_convention` are limited to command-less non-acceptance items;
- review `blocking_findings` can block until repro evidence is recorded;
- `doctor` flags malformed refs, duplicate ids, hash spoofing, and ineffective clears;
- generated reports render accepted risks and user overrides visibly.

For old ledgers, add explicit `resolution_basis`, `clears`, and `evidence_refs` to consensus records
that resolve failed executable checks. Legacy no-basis consensus still defaults to
`non_executable_convention`, which only clears command-less non-acceptance items.
