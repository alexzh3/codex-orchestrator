# Decisions And Consensus

Use a `decision` entry for consequential disagreements, accepted risks, tie-breaks, or required
user action. Do not create one for routine agreement.

Allowed outcomes are:

- `consensus`: Claude and the relevant Codex agent converge after inspecting evidence.
- `claude_decision`: Claude makes the final call and records rationale and risk.
- `user_action_required`: progress or acceptance needs an explicit user choice or external action.

## Independence, Diversity, And Selection

Context independence and model-family diversity are different. This plugin's normal pairing is the
Anthropic Claude family in Claude Code and the OpenAI Codex/GPT family in Codex. Codex-implemented
work receives cross-family evaluation when Claude performs its own verification. An additional
fresh Codex reviewer adds context independence and a complementary lens, but it does not add
model-family diversity. When Claude authored the work, prefer Codex review when a second model
materially reduces risk.

Agent count is never a decision rule. Repeated model claims remain claims unless supported by
distinct inspectable evidence. Select a candidate by acceptance fit, direct evidence, risk,
simplicity, and reversibility—not by which conclusion is more popular. Record the compared sources
in the existing `basis`; do not infer confidence from vote count.

Record the concrete `finding`, chosen `resolution`, supporting `basis` references, and `risk`.
References normally point to verification IDs, execution handoffs, repository files, or evidence
paths. A decision explains how observations were weighed; it does not erase a failed verification.

Journal example:

```jsonl
{"type":"decision","id":"decision-01","task":"task-01","finding":"The original check failed before the fix.","outcome":"consensus","resolution":"The defect was fixed and the same check passed on the next revision.","basis":["check-01","check-02"],"risk":"low","recorded_at":"2026-07-10T14:20:00Z"}
```

## Disagreement Loop

1. State the suspected problem precisely and cite what Claude observed.
2. Send a targeted follow-up to the relevant existing agent; avoid another broad rereview.
3. Independently inspect the response, repository state, and relevant checks.
4. Record a decision only when the outcome affects implementation, acceptance, risk, or user action.
5. If a fix is chosen, assign it and verify it before terminalizing the task.

An agent handoff can support “the agent claimed/agreed with X,” but it cannot prove X is correct.
Prefer repository state and independent checks as the basis for acceptance.

Use `claude_decision` when evidence supports proceeding despite remaining model disagreement. State
the alternative, rationale, and residual risk. Use `user_action_required` only when Claude cannot
safely choose within the user's existing authority; a run with unresolved required user action
normally closes with `judgment: blocked`.
