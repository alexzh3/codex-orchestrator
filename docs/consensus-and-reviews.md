# Consensus and Reviews

This document explains the evidence flow for anyone reading a ledger, checking why `gate` passed or
blocked a run, or interpreting what `doctor` flagged.

## Overview

Every claim about the code must be backed by *recorded evidence*. Agreement alone is not enough to
bypass an unresolved problem. A check is either satisfied, or it **blocks the run** until a
**consensus** record clears it. Clearing a failure requires the right proof for that failure:

- a **runnable check that failed** (test, lint, build…) clears only by **re-running the same command
  until it passes**, or an explicit human override;
- a **judgment call that failed** (a manual review of style, docs, or convention — nothing to re-run)
  clears by **accepting it as a known risk**, or a human override;
- an **acceptance test** — the check that decides whether the task is truly done — is strictest: a
  runnable one clears *only* by passing a real re-run (no overrides), and a non-runnable one cannot
  be cleared at all; it has to actually pass.

`gate` reads the ledger and decides accept/block, `doctor` checks it for integrity problems, and
`report` writes a human-readable summary. Everything below is the reference behind those rules.

**Core records:**

- **verification** — evidence that a check happened, plus its result. The check may be automated (a
  test command) or manual (a `manual_review` recording a maintainer's judgment).
- **review** — a judgment pass over the work as a whole; it can raise **findings**.
- **finding** — one specific problem a review claims, optionally with a command to reproduce it.
- **consensus** — a record that resolves a failed check, finding, or disagreement (see the naming
  note under [Consensus Events](#consensus-events)).
- **gate** — reads the whole ledger and decides whether the run can ship.
- **doctor** — a read-only integrity check over the ledger.

## The Flow

```
task_created + file claims
  -> Codex implementation
  -> verification events for concrete checks
  -> review events for human/agent judgment
  -> consensus events that resolve failures or disagreements
  -> gate decides ship/no-ship from the ledger
  -> doctor audits ledger integrity
  -> report renders the run for humans
```

The ledger is the source of truth: everything `gate` and `doctor` decide comes only from these
records.

## Verification Events

A verification records one piece of evidence:

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

- `kind`: check category — `test`, `lint`, `build`, `typecheck`, `benchmark`, `artifact_check`,
  `screenshot`, `manual_review`, `git_diff`, or `custom`.
- `result`: `passed`, `failed`, `skipped`, `inconclusive`, or `needs_human_review`. `gate` treats
  `failed`, `inconclusive`, and `needs_human_review` as unresolved until a later consensus clears them
  with a valid basis.
- `summary`: plain-text description of what happened.
- `command`: the exact command that was run. Rerun checks compare it after CRLF normalization and
  outer-whitespace stripping, via the shared command hash.
- `command_hash`: `sha256:` plus the hash of the normalized command. `gate` always recomputes it from
  `command` and never trusts a stored hash; a mismatch makes `doctor` emit `command-hash-mismatch`.
- `id`: a non-empty id like `V1`. `add-verification` auto-generates the first unused `Vn`; duplicate
  ids are rejected. Consensus refs use `verification:<id>`.
- `task_id`, `covers_tasks`, `scope`: which task(s) a verification satisfies. Unscoped verifications
  satisfy any task; `scope: "global"` covers the whole run.
- `acceptance_test`: marks it as an acceptance check. Failed acceptance checks cannot be cleared by
  `accepted_risk`, `non_executable_convention`, or `user_override` — only a passing rerun with the
  same command, kind, task, and acceptance flag.
- `attempt_count`: how many attempts this record represents. Missing or invalid counts as 1.
- `stochastic`: when true, `repro_not_reproduced` needs at least **2** passing rerun attempts.
- `exit_code`: the process exit code, if any.
- `artifacts`: paths or names that back the verification.
- `finding_id`: links a repro run to a review finding. `gate` counts it as repro evidence only when the
  `finding_id` matches, it comes later in the ledger than the review that filed the finding, and it
  ran the finding's exact `repro_command`.

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

`gate` appends a `gate_result` and exits nonzero when blocking reasons remain. `doctor` runs
read-only integrity checks and never mutates the ledger. `report --strict` renders `report.md` and
fails if required sections still contain missing-evidence placeholders.

## Review Events And Blocking Findings

A review records a judgment. It may include legacy free-form `findings` and structured
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

- `id`: non-empty id, referenced as `finding:<id>`.
- `claim`: the concrete claim.
- `severity`: `P0`, `P1`, or `P2`; default is `P1`.
- `file_refs`: optional file references.
- `repro_command`: the exact command a later verification must run to count as repro evidence.
- `min_repro_attempts`: required passing attempts (positive integer, default 1).

Finding lifecycle:

1. A review files a P0 or P1 finding with `repro_command`.
2. `gate` emits `pending-repro` until valid repro evidence is recorded, or until a later
   `accepted_risk`/`user_override` consensus clears it by `finding:<id>`.
3. A later verification with the matching `finding_id` and exact `repro_command` counts as repro
   evidence. If that verification *failed*, it blocks as `unresolved-verification` (`gate` will not
   also count it as `pending-repro`).
4. Once enough later passing attempts are recorded, the finding stops blocking.
5. P2 findings never block. A P0/P1 finding *without* `repro_command` does not block either, but
   `gate` warns `finding-no-repro-command` and `doctor` emits `finding-missing-repro`.
6. A later review can re-file the same finding id; `gate` evaluates each occurrence independently,
   so an earlier clear does not clear a later re-file.

## Consensus Events

In the ledger, a `consensus` record means **"resolution record"**. It may capture true agreement
between Claude and Codex, a Claude decision, or a request for user action, so not every consensus
record is literal consensus. Each one records how a failed check, finding, or
disagreement was resolved.

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

- `consensus`: Claude and Codex agree after weighing the evidence.
- `claude_decision`: Claude proceeds with a recorded rationale.
- `user_action_required`: a human must act. This never resolves a gate blocker.

`requires_user: true` also stops the consensus from clearing anything, regardless of `outcome`.

**Resolution bases:** the reason a consensus gives for clearing a failure.

| Basis | In plain words | Use when | Can clear |
| --- | --- | --- | --- |
| `rerun_passed` | The same command was run again and passed. | A runnable check failed, then passed on re-run. | Failed runnable or acceptance checks — only with a valid rerun link. |
| `repro_not_reproduced` | A flaky check stopped failing when re-run. | A flaky (`stochastic`) check was re-run enough times. | Same as `rerun_passed`, but flaky checks need 2 passing attempts. |
| `accepted_risk` | A judgment call (nothing to re-run) is accepted as a known risk. | The issue is a convention, documentation, or policy call. | Command-less non-acceptance failures, and findings by `finding:<id>`. |
| `non_executable_convention` | The older/default label for `accepted_risk`, mainly for old run records. | Legacy ledgers, or when no basis was given. | Command-less non-acceptance failures. |
| `user_override` | A human decided to accept the outcome anyway. | An explicit human call. | Runnable non-acceptance failures and findings. It cannot clear acceptance tests. |

`clears` lists what the consensus resolves. It is addressed by ref, and a non-empty `clears` never
falls back to text matching. `evidence_refs` points to proof records, but never clears a verification
on its own. Both use `verification:<id>` and `finding:<id>` refs.

A consensus with no `resolution_basis` defaults to `non_executable_convention`, which only clears
command-less, non-acceptance items — this keeps old ledgers working.

## The Clear Matrix

Which clearing method is allowed depends on two things about the failed check:

1. **Does it have a command?** If yes, you can re-run it to prove it passes now. If no, it's a
   judgment call with nothing to re-run.
2. **Is it an acceptance test?** — the check that decides whether the task is actually done.

The rule is *match the proof to the failure*: re-run and pass a runnable failure; accept the risk on
a judgment call; and never clear an acceptance test unless it genuinely passes.

| Verification failure | `rerun_passed` | `repro_not_reproduced` | `accepted_risk` | `non_executable_convention` | `user_override` |
| --- | --- | --- | --- | --- | --- |
| Executable command, not acceptance | Clears with valid rerun | Clears with valid rerun and enough attempts | Blocks | Blocks | Clears |
| Acceptance test with command | Clears with valid rerun | Clears with valid rerun and enough attempts | Blocks | Blocks | Blocks |
| Command-less, not acceptance | Blocks | Blocks | Clears | Clears | Clears |
| Command-less acceptance test | Blocks | Blocks | Blocks | Blocks | Blocks |

A valid rerun link requires all of:

- the linked verification result is `passed`;
- it is recorded earlier in the ledger than the consensus that cites it;
- its `recorded_at` is parseable and strictly newer than the failed verification;
- same `task_id` (missing counts as empty);
- same `kind`;
- both records have a non-empty `command`;
- `computed_command_hash(link.command) == computed_command_hash(failed.command)`;
- same `acceptance_test` value;
- the linked id resolves to exactly one record, not a duplicate;
- linked `attempt_count` meets the basis minimum.

## Worked Examples

### A failed test cleared by a rerun

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

`gate` accepts this only if `V2` was recorded before the consensus, has result `passed`, is strictly
newer than `V1`, and matches `V1` on kind, task, command hash, and acceptance flag — with no
duplicate id.

### Accepted risk over a style convention

A `manual_review` verification `V1` fails with no command and is not an acceptance test. A consensus
clears it with:

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

The same consensus would **not** clear a failed test command or an acceptance check.

### Plain agreement cannot clear a failed executable test

A failed test verification has a command. A later consensus with matching text but no basis, `clears`
ref, or rerun evidence does **not** clear it — `gate` emits `unresolved-verification`.

### A finding cleared by repro attempts

A review files `F1` as P1 with `repro_command` and `min_repro_attempts: 3`. Later, passing
verifications with `finding_id: "F1"` run that exact command after the review; once their total
`attempt_count` reaches 3, the finding stops blocking. Alternatively, a later consensus with
`resolution_basis: "accepted_risk"` and `clears: ["finding:F1"]` clears it by explicit ref.

## Reference: Gate And Doctor Codes

**Gate blocking reasons:**

- `malformed-ledger`: a ledger line is not valid JSON.
- `missing-report`: `report.md` does not exist.
- `stale-report`: `report.md` is older than the latest non-gate ledger event.
- `file-claim-conflict`: active file claims overlap.
- `unclaimed-change`: a completed task changed a path outside its allowlist.
- `active-task`: a task is not in a terminal status.
- `missing-checkpoint`: a completed task has no `task_checkpoint`.
- `unmet-verification`: a completed task has an unsatisfied `verification_required` entry.
- `unresolved-verification`: a failed, inconclusive, or human-review verification lacks a later valid
  resolving consensus.
- `pending-repro`: a P0/P1 blocking finding still lacks enough later passing repro evidence.
- `unresolved-consensus`: a consensus still requires user action.
- `missing-final-review`: no passing run-wide final review is recorded.

**Gate warnings:**

- `low-parser-confidence`: a monitored session has low parser confidence.
- `finding-no-repro-command`: a P0/P1 blocking finding lacks `repro_command`, so it cannot block.

**Doctor checks:**

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
