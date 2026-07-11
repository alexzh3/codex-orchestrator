# Claims, Evidence, And Review

For Claude's own verification, read an agent handoff first. It is the agent's compact claim
package: status, summary, files changed, claims or findings, commands it reports running, and
caveats. It is not proof that those claims are true. A first-pass independent Codex reviewer has a
different information diet, defined below.

Evidence is an inspectable observation used to support or contradict a verification or decision.
Prefer evidence in this order:

1. Direct observations: repository diff, command exit/result, screenshot, measured output.
2. Mechanically derived observations whose source remains available.
3. Manual or model review observations tied to exact files or behavior.
4. Agent claims, which identify what to inspect but do not establish correctness.

Prompts establish assigned scope. Event streams establish what a session emitted and are useful for
monitoring or debugging. Neither is independent evidence that the implementation works.

## Verification

Claude records a `verification` only after evaluating a concrete task criterion. Include:

- a unique `id`, such as `check-01`;
- the `task` and criterion;
- the method, such as `command`, `diff_review`, `visual`, or `manual`;
- the exact command or inspection under `check`;
- `result`: `passed`, `failed`, `inconclusive`, or `skipped`;
- a concise factual `observation`;
- optional `evidence` paths when the underlying material should be retained.

Small observations belong inline. Save full output under `evidence/` when it is lengthy, binary,
disputed, failure-diagnostic, or important to audit. Do not create extracted agent-response files:
the exact handoff already records the agent's claims.

If a command fails, preserve the failure, fix the cause, rerun the relevant command, and record a
new verification. Do not rewrite the failed record or claim that a passing rerun erases history.
Claude explains the relationship in a later `decision` and in `run_closed`.

## Review Loop

1. Read the handoff and inspect the actual changed files and diff.
2. Compare the `execution_result.files_changed` note and the actual diff with the task's
   allowed/owned paths or globs in `files`.
3. Independently run checks needed by the acceptance criteria. Never promote
   `Commands Reported` from a handoff directly to a passing verification.
4. If Claude finds a material issue, send the exact finding and observed evidence back to the same
   relevant agent in a new execution.
5. Record the resulting agreement, Claude judgment, or need for user input as a `decision`.
6. Repeat only for unresolved material issues, then record the terminal task status.

Watch for failure spirals: weakened assertions, deleted inputs, narrowed ranges, or special-cased
validation failures. For nondeterministic work, prefer seeds, thresholds, and regression bands over
accepting one lucky pass.

## Independent Codex Review

Use Codex review when a second model materially reduces risk. The first independent review must be
unprimed by the implementer's narrative. Start a fresh named `codex-review-NN` agent and native
session; never resume the implementation session. Give it the original goal, acceptance criteria,
relevant constraints, exact review target, and one primary review lens. Do not include the
implementer handoff, claimed test results, earlier review verdicts, or Claude's tentative conclusion
unless the task is specifically to evaluate one of those claims. Claude still reads the handoff for
its own verification, but must not relay it into this first-pass prompt.

An unanchored alternative is candidate generation rather than review: give a fresh agent the goal,
criteria, and constraints before showing it Claude's candidate, then compare the proposals after
both exist.

Choose a lens that complements the material risk, such as behavior and acceptance, regression
coverage, security and trust boundaries, API and architecture, concurrency and performance, or
visual and UX behavior. Save the review prompt first, append its execution, then capture both the
event stream and handoff:

```bash
"$CODEX" exec -C <worktree> -s workspace-write review --json \
  --output-last-message "$EXECUTION_DIR/handoff.md" \
  --commit <sha> - \
  < "$EXECUTION_DIR/prompt.md" \
  > "$EXECUTION_DIR/events.jsonl"
```

Prefer `--commit <sha>` because the reviewed source is immutable and needs no source-file write
reservation; normal shared-resource isolation still applies. Use `--base <branch>` only when the
reviewed head is stable; otherwise create a commit and use `--commit`. For `--uncommitted`, record
the base HEAD SHA and reserve only the reviewed task's files and shared resources as described in
`compute.md`; disjoint work may continue. If that scoped reservation cannot be maintained, use a
separate worktree or commit a stable snapshot. Target the repository being reviewed with `-C`; if
the shell runs elsewhere, make `EXECUTION_DIR` absolute so prompt, event, and handoff paths still
refer to the run directory.

Represent a monitored review as a named review agent and execution, with its exact prompt/event
source/handoff. Treat review findings as claims until Claude checks them against the repository.
Codex agreement is useful corroboration, not a substitute for relevant executable checks. A
targeted recheck may reuse that review session. A fresh tie-break described as independent must use
a new session, and another reviewer is worthwhile only when it answers a distinct unresolved
question rather than repeating the same broad review.
