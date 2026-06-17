---
description: Run the full Claude-Codex orchestration workflow from setup through review, verification, consensus, and report.
---

# Workflow

Use this command when Claude should run the full Codex orchestration workflow end to end.

Use when: you want one coordinated run that initializes durable state, supervises or drives Codex,
reviews the result, records evidence, resolves disagreements, and writes the final report.

Do not use when: you only need to create the run ledger. Use `/codex-orchestrator:start-run` for
setup-only initialization.

Scope: full run. This command should initialize or reuse a run ledger, inspect session/repo state,
monitor or drive Codex as needed, review diffs, record verification evidence, resolve consensus when
there is a suspected issue, and generate `report.md`.

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

Use `commands/start-run.md` only for setup. Follow `skills/codex-orchestrator/SKILL.md` for the
full operating rules.
