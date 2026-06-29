# Consensus Outcomes

When Claude and Codex disagree about a reviewed plan or result, record the evidence and choose one
outcome:

- `consensus`: evidence resolves the disagreement and Claude/Codex converge on the same fix,
  no-fix rationale, or acceptance decision.
- `claude_decision`: Claude proceeds despite unresolved disagreement, with recorded rationale,
  risk level, and verification requirements.
- `user_action_required`: Claude is not confident enough to continue or accept without user input.

## Required Evidence

For each consensus record, capture:

- The suspected issue or disagreement.
- The exact evidence inspected: diff, tests, logs, manifests, generated artifacts, benchmark output,
  or parser state.
- Codex's response or review result.
- Whether Claude and Codex agree, disagree, or partially agree.
- Root cause when known.
- Chosen fix or no-fix rationale.
- Risk level.
- Whether user input is required.
- Verification required before acceptance.

## Plan Review Disagreements

For `/codex-orchestrator:workflow`, have Codex review any new Claude-created plan before execution.
For focused `/codex-orchestrator:orchestrate` phases, request plan review only when the user asks or
risk warrants a second opinion before dispatch.

If planning disagreement remains, record the evidence and choose one outcome: `consensus` when
evidence resolves it, `claude_decision` when Claude proceeds with recorded rationale/risk, or
`user_action_required` when Claude is not confident enough to continue or accept without user input.

## Review Disagreements

If Claude finds a suspected issue after Codex implementation, share the exact finding, evidence, and
proposed resolution with Codex before implementing or accepting a fix. Use targeted consensus
prompts, not another broad rereview:

```bash
"$CODEX" exec resume <thread-id> "<specific finding, evidence, and proposed fix>"
```

After accepted fixes, run Claude's final review and a Codex final review. Accept when both final
reviews pass or when Claude records `claude_decision` after the evidence review.

Record consensus evidence in `ledger.jsonl` and ensure it appears in the generated `## Consensus`
section of `report.md`. Save the exact consensus prompt under `prompts/` and the captured JSONL under
`logs/` with a matching stem.
