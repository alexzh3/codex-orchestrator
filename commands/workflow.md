---
description: Reuse or dispatch Codex exec agents, monitor them, then review, verify, resolve consensus, and report.
---

# Workflow

Use this command when Claude should run Codex orchestration. This is the main command for both the
full end-to-end run and scoped workflow phases.

Use when: you want one coordinated run that initializes durable state, reuses or resumes matching
Codex exec agents, dispatches new agents only when needed, monitors their JSONL streams or an
existing IDE thread, reviews the result, records evidence, resolves disagreements, and writes the
final report. Also use this command with a scoped prompt when you want only one active orchestration
phase, such as monitoring, review, consensus, handoff, or compute gating.

Do not use when: you only need to open a run ledger. Use `/codex-orchestrator:start-run` for
setup-only initialization.

Scope: full run. This command should initialize or reuse a run ledger, inspect session/repo state,
reuse matching named Codex agents before spawning new ones, split the work into bounded Codex
prompts, run `codex exec --json` subagents only when a new agent is needed, monitor each stream with
parser state/tail offsets, review diffs, record verification evidence, resolve consensus when there
is a suspected issue, and generate `report.md`.

Public command surface: `workflow`, `start-run`, and `report`. Monitoring, review, consensus,
handoff, and compute-gating are internal workflow phases, not separate slash commands.

Default workflow:

```text
1. Create or reuse a run id.
2. Initialize state.json, ledger.jsonl, and report.md if needed.
3. Inspect existing named Codex agents in state/ledger and classify their current status.
4. Scope Codex tasks and map each task to an existing agent when the role/context matches.
5. Resume matching idle/complete agents; keep monitoring active ones.
6. Start a new `codex exec --json` agent only for unrelated work, full/irrelevant context, required isolation, or explicit user request.
7. Monitor each session with parser state/tail offsets without loading full rollout logs.
8. Review code, diffs, logs, and artifacts.
9. Run or inspect verification checks.
10. Record verification and material events in ledger.jsonl.
11. Record consensus findings if Claude and Codex disagree.
12. Generate or update report.md.
```

Use `commands/start-run.md` only for the setup step inside this workflow. Follow
`skills/codex-orchestrator/SKILL.md` for the full operating contract and concrete procedures.
