# Claims, Evidence, And Review

Read an agent handoff first. It is the agent's compact claim package: status, summary, files
changed, claims or findings, commands it reports running, and caveats. It is not proof that those
claims are true.

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

Use Codex review when a second model materially reduces risk. Save the review prompt first, append
its execution, then capture both the event stream and handoff:

```bash
"$CODEX" exec review --json \
  --output-last-message "$EXECUTION_DIR/handoff.md" \
  --uncommitted - \
  < "$EXECUTION_DIR/prompt.md" \
  > "$EXECUTION_DIR/events.jsonl"
```

Use the same command with `--base <branch>` instead of `--uncommitted` to review changes against a
branch, or `--commit <sha>` to review one commit.

Represent a monitored review as a named review agent and execution, with its exact prompt/event
source/handoff. Treat review findings as claims until Claude checks them against the repository.
Codex agreement is useful corroboration, not a substitute for relevant executable checks.
