---
name: codex-orchestrator-workflow
description: Run the full Codex orchestration workflow end to end.
---

# Workflow

Use this skill when Claude should run the full Codex orchestration workflow end to end: ledger
setup, planning, dispatch, monitoring, review, verification, consensus, and report.

Use when the user wants one coordinated run that initializes durable state, reuses or resumes
matching Codex agents, dispatches new agents only when needed, monitors their JSONL streams or an
existing IDE thread, reviews the result, records evidence, resolves disagreements, and writes the
final report.

Do not use this skill for a single focused phase such as monitoring, review, consensus, handoff, or
compute gating. Use `${CLAUDE_PLUGIN_ROOT}/skills/orchestrate/SKILL.md` for those. For explicit
ledger-only setup, run the internal CLI init helper and stop.

Default workflow:

1. Create or reuse a run id.
2. Initialize `state.json`, `ledger.jsonl`, `report.md`, `prompts/`, `logs/`, and `artifacts/` if
   needed.
3. Inspect existing named Codex agents in state/ledger and classify their current status.
4. If no usable plan exists, create a minimal orchestration plan for Codex agents.
5. Have Codex review any new Claude-created plan before execution; if planning disagreement remains,
   record `consensus`, `claude_decision`, or `user_action_required`.
6. Scope tasks and dispatch implementation/repair/refactor/test-writing to Codex, reusing matching
   agents when role/context fits.
7. Start a new headless Codex agent with `codex exec --json` only for unrelated work, full or
   irrelevant context, required isolation, or explicit user request.
8. Save each Codex prompt under `prompts/` and capture each Codex JSONL stream under `logs/` using
   matching stems.
9. Monitor each session with parser state/tail offsets without loading full rollout logs.
10. Review code, diffs, logs, and artifacts yourself after Codex yields or completes.
11. Obtain an independent Codex review of the diff before acceptance.
12. Run or inspect verification checks and record verification, consensus, and final report state.
13. Generate or update `report.md`.

Follow `${CLAUDE_PLUGIN_ROOT}/skills/orchestrate/SKILL.md` for the full operating contract and
concrete procedures.
