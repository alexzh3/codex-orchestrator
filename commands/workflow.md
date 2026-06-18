---
description: Run the full Codex orchestration workflow end to end, including ledger, planning, dispatch, monitoring, review, verification, consensus, and report.
---

# Workflow

Use this command when Claude should run the full Codex orchestration workflow end to end.

Use when: you want one coordinated run that initializes durable state, reuses or resumes matching
Codex agents, dispatches new agents only when needed, monitors their JSONL streams or an
existing IDE thread, reviews the result, records evidence, resolves disagreements, and writes the
final report.

Do not use when: you only need a scoped orchestration phase such as monitoring, review, consensus,
handoff, or compute gating. Use `/codex-orchestrator:orchestrate` with a focused prompt for that.
For explicit ledger-only setup, run the internal CLI init helper and stop.

Scope: full run. This command should initialize or reuse a run ledger, inspect session/repo state,
reuse matching named Codex agents before spawning new ones, split the work into bounded Codex
prompts, have Codex review any new Claude-created plan before execution, launch new workers with
`codex exec --json` only when a new agent is needed, monitor each stream with parser state/tail offsets,
review diffs after Codex yields or completes, record verification evidence, resolve consensus when
there is a suspected issue, and generate `report.md`.

Public entry points: `orchestrate`, `workflow`, and `report`. Monitoring, review, consensus,
handoff, compute-gating, and ledger initialization are orchestration phases requested through
`orchestrate` or performed inside a full `workflow`, not separate slash commands.

Default workflow:

```text
1. Create or reuse a run id.
2. Initialize state.json, ledger.jsonl, report.md, prompts/, logs/, and artifacts/ if needed.
3. Inspect existing named Codex agents in state/ledger and classify their current status.
4. If no usable plan exists, create a minimal orchestration plan for Codex agents.
5. Have Codex review any new Claude-created plan before execution; if planning disagreement remains, record the evidence and choose one outcome: `consensus` when evidence resolves it, `claude_decision` when Claude proceeds with recorded rationale/risk, or `user_action_required` when Claude is not confident enough to continue or accept without user input.
6. Scope tasks and dispatch implementation/repair/refactor/test-writing to a Codex agent; map each task to an existing agent when the role/context matches.
7. Resume matching idle/complete agents; compact first when a relevant session is almost full. Keep monitoring active ones.
8. Start a new headless Codex agent with `codex exec --json` only for unrelated work, full/irrelevant context, required isolation, or explicit user request.
9. Save each Codex prompt under prompts/ and capture each Codex JSONL stream under logs/ using matching stems.
10. Monitor each session with parser state/tail offsets without loading full rollout logs.
11. Review code, diffs, logs, and artifacts yourself after Codex yields or completes.
12. Obtain an independent Codex review of the diff before acceptance (`codex exec review`), not only on a suspected issue; if Claude proceeds via `claude_decision`, record the evidence, rationale, risk level, and verification.
13. Run or inspect verification checks and record verification (including the Codex review) in ledger.jsonl.
14. Resolve any Claude/Codex disagreement with evidence and record `consensus`, `claude_decision`, or `user_action_required` durably.
15. Generate or update report.md.
```

Follow `${CLAUDE_PLUGIN_ROOT}/commands/orchestrate.md` for the full operating contract and concrete
procedures.
