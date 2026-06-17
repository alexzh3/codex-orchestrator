---
description: Run the full Claude-Codex orchestration workflow from setup through review, verification, consensus, and report.
---

# Workflow

Use this command when Claude should run Codex orchestration. This is the main command for both the
full end-to-end run and scoped workflow phases.

Use when: you want one coordinated run that initializes durable state, supervises or drives Codex,
reviews the result, records evidence, resolves disagreements, and writes the final report. Also use
this command with a scoped prompt when you want only one active orchestration phase, such as
monitoring, review, consensus, handoff, or compute gating.

Do not use when: you only need to open a run ledger. Use `/codex-orchestrator:start-run` for
setup-only initialization.

Scope: full run. This command should initialize or reuse a run ledger, inspect session/repo state,
monitor or drive Codex as needed, review diffs, record verification evidence, resolve consensus when
there is a suspected issue, and generate `report.md`.

Public command surface: `workflow`, `start-run`, and `report`. Monitoring, review, consensus,
handoff, and compute-gating are internal workflow phases, not separate slash commands.

Default workflow:

```text
1. Create or reuse a run id.
2. Initialize state.json, ledger.jsonl, and report.md if needed.
3. Locate or start the relevant Codex IDE or exec session.
4. Monitor session state without loading full rollout logs.
5. Review code, diffs, logs, and artifacts.
6. Run or inspect verification checks.
7. Record verification and material events in ledger.jsonl.
8. Record consensus findings if Claude and Codex disagree.
9. Generate or update report.md.
```

Use `commands/start-run.md` only for the setup step inside this workflow. Keep
`skills/codex-orchestrator/SKILL.md` in context as the compact operating contract, and open only the
reference files needed for the current step:

```text
skills/codex-orchestrator/references/run-ledger.md
skills/codex-orchestrator/references/live-session-monitoring.md
skills/codex-orchestrator/references/codex-exec.md
skills/codex-orchestrator/references/review-consensus.md
skills/codex-orchestrator/references/multi-session-compute.md
```
