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
- Save the prompt and append the execution before launch. Let the runner capture the event stream
  and Codex save the exact handoff.

```bash
EXECUTION_DIR=".codex-orchestrator/runs/<run-id>/codex-review-01/execution-01"
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/codex_orch_tools.py" run \
  --label codex-review-01 \
  --events "$EXECUTION_DIR/events.jsonl" \
  --prompt "$EXECUTION_DIR/prompt.md" \
  -- codex exec -C <worktree> -s workspace-write -c approval_policy=never --json \
     --output-last-message "$EXECUTION_DIR/handoff.md" -
```

Launch this as a Claude Code background Bash task. The runner creates `events.jsonl` exclusively
and aborts on a pre-existing file, captures raw Codex stdout there byte-for-byte, and prints only
compact one-line progress to its own stdout for the human `/tasks` view. Codex stderr passes
through for native diagnostics. After a clean capture, the runner exits with Codex's exit code.
Capture, prompt, or launch failures exit nonzero; cancellation exits with 128 plus the signal
number. Everything after `--`, including this review command, passes to Codex unchanged.

Write the exact commit SHA into `prompt.md` and instruct Codex to review that snapshot. Use plain
`codex exec`: the Codex CLI does not accept a stdin review prompt together with the `review`
subcommand's revision selectors. Prefer a worktree at the reviewed commit; reviewing a fixed SHA
does not require pausing unrelated work. Tell Codex not to edit and confirm the review worktree is
clean afterward; `workspace-write` lets repository checks create their normal temporary outputs.

For an uncommitted review, put the base HEAD SHA and exact reviewed files in `prompt.md`, run the
same plain `codex exec` command in that working tree, and reserve those files and shared resources
as described in [`compute.md`](compute.md).

Verify review findings against the repository. Reuse the session for a targeted recheck; start a
fresh reviewer only for a distinct unresolved question.
