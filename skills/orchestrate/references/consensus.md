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

## Resolution Basis

For 0.4.0+ consensus records that resolve failed verification or review evidence, include a
machine-checkable `resolution_basis` plus refs:

- `rerun_passed`: a later verification reran the identical command string and passed.
- `repro_not_reproduced`: a stochastic failure did not reproduce; stochastic checks need 2 passing
  attempts.
- `accepted_risk`: a command-less, non-acceptance convention or risk is accepted.
- `non_executable_convention`: legacy/default basis for command-less convention decisions.
- `user_override`: explicit human approval. Use only after the human says to override; it is
  rendered loudly and counted in the report.

Use `clears` for what the consensus resolves and `evidence_refs` for proof:

```json
{
  "resolution_basis": "rerun_passed",
  "clears": ["verification:V1"],
  "evidence_refs": ["verification:V2"]
}
```

Rerun flow: record the failed check and keep its auto id (`V1`), rerun with the identical command
string, record the passing rerun (`V2`), then add consensus with `rerun_passed`, `clears:
["verification:V1"]`, and `evidence_refs: ["verification:V2"]`.

Traps:

- `user_override` with `requires_user: true` resolves nothing.
- A consensus with non-empty `clears` never falls back to text matching.
- `evidence_refs` never address what is being cleared.
- Acceptance-test failures are cleared only by a green rerun with the same command/kind/task and
  matching acceptance flag; `user_override` does not clear them.

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
