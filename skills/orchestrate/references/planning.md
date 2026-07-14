# Planning And Plan Review

Use [the orchestration contract](../../../docs/orchestration-contract.md) for journal fields. Both
roles are optional, risk-gated inputs to Claude's planning process. Claude owns the draft and final
plan, decides how to resolve findings, and remains responsible for verification and closure.

## Independent Planning

Use `planning` for an independent approach before Claude locks a consequential or hard-to-reverse
design choice:

- Start a fresh named `codex-plan-NN` agent and native session with a read-only sandbox.
- Provide only the goal, constraints, acceptance criteria, and repository location needed for
  grounded inspection. Do not provide Claude's draft plan, another agent's proposal, or a tentative
  verdict.
- Ask for a bounded proposal covering the approach, material assumptions, risks, and verification
  path. Do not ask the agent to edit the repository.
- Append `execution` before launch and preserve its exact prompt, events, and handoff.

This configured example uses `max` for one coherent planning question:

```bash
EXECUTION_DIR=".codex-orchestrator/runs/<run-id>/codex-plan-01/execution-01"
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/codex_orch_tools.py" run \
  --label codex-plan-01 \
  --repo <repo> \
  --role planning \
  --reasoning-effort max \
  --events "$EXECUTION_DIR/events.jsonl" \
  --prompt "$EXECUTION_DIR/prompt.md" \
  -- codex exec -C <worktree> -s read-only -c approval_policy=never --json \
     --output-last-message "$EXECUTION_DIR/handoff.md" -
```

Launch it as a Claude Code background Bash task whose title is the exact named agent, such as
`codex-plan-01`. Keep `--label` in the starting command for compatibility and launch-command
visibility; the runner does not repeat it on every progress line.

## Plan Review

Use `planning_review` only after Claude has a concrete draft that would benefit from an independent
critique:

- Start a separate fresh named `codex-plan-review-NN` agent and native session with a read-only
  sandbox. Never reuse the independent-planning, implementation, or implementation-review session.
- Provide the goal, constraints, acceptance criteria, and exact draft plan. Do not provide the
  independent planner's handoff, earlier review verdicts, or Claude's tentative response to likely
  findings.
- Ask it to identify correctness gaps, missing decisions, unjustified assumptions, risky sequencing,
  and inadequate acceptance checks. Do not ask it to implement fixes.
- Treat the handoff as claims and resolve material findings from repository evidence. Do not accept
  or reject a finding by agent count.

This configured example uses a different persistent agent and role:

```bash
EXECUTION_DIR=".codex-orchestrator/runs/<run-id>/codex-plan-review-01/execution-01"
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/codex_orch_tools.py" run \
  --label codex-plan-review-01 \
  --repo <repo> \
  --role planning_review \
  --reasoning-effort max \
  --events "$EXECUTION_DIR/events.jsonl" \
  --prompt "$EXECUTION_DIR/prompt.md" \
  -- codex exec -C <worktree> -s read-only -c approval_policy=never --json \
     --output-last-message "$EXECUTION_DIR/handoff.md" -
```

Launch it as a separate background Bash task titled `codex-plan-review-01`; as with planning, keep
the matching `--label` in the starting command without repeating it in progress output.

For either role, use `ultra` instead of `max` only for broad, multi-domain, context-heavy, or
parallelizable analysis. Nested subagents created during an Ultra execution inherit the parent
execution's sandbox and ownership boundaries and remain part of that named execution; do not give
them separate journal identities.

The examples assume an active role configuration. If `.codex-orchestrator/config.ini` is absent,
retain `--repo` and `--role`, omit `--reasoning-effort`, and let native Codex configuration apply
without creating a policy. A targeted clarification may resume its own relevant idle session, but
the initial planning and plan-review passes must always be separate fresh sessions.
