# Review And Consensus Reference

Use this when accepting Codex output, recording verification, or resolving a Claude-Codex
disagreement.

## Acceptance Review

Treat code and artifacts as source of truth, and narration as intent. Verify claims against the
working tree, `git show`, generated manifests, logs, and test output before accepting them.

Watch for failure spirals: repeatedly shrinking ranges, deleting inputs, weakening assertions, or
special-casing validation failures may hide the root cause. Flag the pattern, not only the latest
edit.

Append running review notes to the `## Review` section of `report.md`, append material events to
`ledger.jsonl`, and update `state.json` when review status changes.

## Verification Evidence

Record checks through the ledger CLI:

```bash
python3 scripts/codex_orch.py add-verification --run-id <run-id> --kind test --command "<cmd>" --exit-code <n> --result passed --summary "<summary>"
```

For deterministic code changes, inspect diffs and run the most relevant test, lint, typecheck, build,
or manifest assertion available.

For nondeterministic training or rollout changes, require seeded determinism where applicable,
metric-threshold checks on eval rollouts, and regression bands on reward/return rather than equality
assertions. Do not accept training-affecting changes on one stochastic pass.

## Consensus Protocol

When Claude finds a suspected Codex mistake, share the specific finding back with Codex before
implementing or accepting the fix. The suspicion may be wrong, or Codex may have task context Claude
has not considered.

Use one of:

```bash
"$CODEX" exec review --uncommitted
"$CODEX" exec resume <thread-id> "<specific finding, evidence, and proposed fix>"
```

Resolve with evidence, not majority vote. Record the suspected issue, evidence, root cause when
known, agreed resolution, and verification as a `consensus` record in `ledger.jsonl` and in the
`## Consensus` section of `report.md`.

Do not interrupt a live Codex turn just because you noticed a possible issue. Record the observation
and prepare a paste-ready steer; inject it only when the session is idle.
