# Review Loop

Treat code, diffs, tests, logs, manifests, and generated artifacts as source of truth. Treat agent
narration as intent until verified. Watch for failure spirals: weakened assertions, deleted inputs,
shrunk ranges, or special-cased validation failures.

For deterministic changes, inspect diffs and run relevant tests, typecheck, lint, build, or manifest
assertions. For nondeterministic rollout/training changes, require seeded determinism where possible,
metric thresholds, and regression bands; do not accept one stochastic pass.

## Independent Codex Review

Run `codex exec review --uncommitted` or the relevant `--commit <sha>` / `--base <branch>` form as
the standard Codex final review before acceptance whenever a diff exists.

```bash
"$CODEX" exec review --uncommitted
"$CODEX" exec review --base <branch>
"$CODEX" exec review --commit <sha>
```

A `claude_decision` outcome must still record evidence, rationale, risk level, and verification.

Save every Codex review or consensus prompt under `prompts/` before running it, and capture its JSONL
output under `logs/` with the same filename stem. Reference both paths from the review or consensus
ledger record.

## Consensus-Gated Review Loop

Use this loop after Codex yields or completes:

1. Codex implements the scoped change.
2. Claude reviews the actual diff, tests, logs, manifests, and artifacts.
3. If Claude finds a suspected issue, share the exact finding, evidence, and proposed resolution
   with Codex before implementing or accepting a fix.
4. Record the outcome: `consensus`, `claude_decision`, or `user_action_required`; whether Claude and
   Codex agree, disagree, or partially agree; root cause when known; chosen fix or no-fix rationale;
   risk level; whether user input is required; and the verification required.
5. Implement accepted fixes, then run Claude's final review and a Codex final review.
6. Accept when both final reviews pass or when Claude records `claude_decision` after the evidence
   review. Use `user_action_required` only when Claude needs user input before continuing or
   accepting.

When Claude needs Codex consensus on a finding, use a targeted prompt rather than another broad
rereview:

```bash
"$CODEX" exec resume <thread-id> "<specific finding, evidence, and proposed fix>"
```

Do not chain broad rereviews. If a final review still finds incorrect behavior after consensus
fixes, run one scoped rereview/fix loop for the unresolved issue and record why the extra pass was
needed. Escalate to the user instead of continuing open-ended review rounds.

Record suspected issue, root cause when known, outcome, and verification as `consensus` evidence in
both `ledger.jsonl` and the `## Consensus` section of `report.md`.
