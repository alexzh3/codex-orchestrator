# Review And Verification

Use [the orchestration contract](../../../docs/orchestration-contract.md) for journal fields.

## Verify Agent Work

1. Read the handoff as claims.
1. Inspect the actual diff and changed files. Compare them with the task's declared `files`.
1. Evaluate every acceptance criterion with an observed check. Do not promote `Commands Reported`
   to a passing verification.
1. Record each criterion as a `verification`.
1. On failure, preserve the record, send the exact finding and observation to the relevant agent,
   and record the recheck separately.
1. Mark the task terminal only after all criteria are evaluated.

Base verification on repository state or observed output. Use handoffs and model findings to choose
what to inspect. Keep concise observations inline; use `evidence/` only for lengthy material worth
retaining.

## Independent Codex Review

For the first independent review:

- Start a fresh named `codex-review-NN` agent and native session; never resume the implementation
  session.
- Provide the goal, acceptance criteria, constraints, and exact review target.
- Do not provide the implementer handoff, claimed test results, earlier review verdicts, or Claude's
  tentative conclusion.
- Save the prompt and append the execution before launch. Capture the event stream and exact
  handoff.

```bash
EXECUTION_DIR=".codex-orchestrator/runs/<run-id>/codex-review-01/execution-01"
codex exec -C <worktree> -s workspace-write review --json \
  --output-last-message "$EXECUTION_DIR/handoff.md" \
  --commit <sha> - \
  < "$EXECUTION_DIR/prompt.md" \
  > "$EXECUTION_DIR/events.jsonl"
```

Prefer `--commit <sha>`. Use `--base <branch>` only for a stable head. For `--uncommitted`, record
the base HEAD SHA and follow [`compute.md`](compute.md) for scoped reservations; otherwise use a
worktree or committed snapshot.

Verify review findings against the repository. Reuse the session for a targeted recheck; start a
fresh reviewer only for a distinct unresolved question.
