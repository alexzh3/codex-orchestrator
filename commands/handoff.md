---
description: Prepare a safe scoped handoff to another Codex session, including worktree separation when needed.
---

# Handoff

Use this command to prepare a safe handoff to another Codex session.

Use when: you are starting or resuming Codex with a scoped prompt, especially for parallel work that
should happen in a separate worktree.

Do not use when: shared GPU, Docker, Isaac, Kit, or training resources may still be busy. Run
`/codex-orchestrator:gate-compute` first.

For parallel work, create a separate worktree first:

```bash
python3 scripts/codex_orch_worktree.py --name codex-a
```

Then resume or start Codex with a scoped prompt:

```bash
"$CODEX" exec -s workspace-write -c approval_policy=never "<prompt>"
"$CODEX" exec resume <thread-id> "<prompt>"
```

References:

```text
skills/codex-orchestrator/references/codex-exec.md
skills/codex-orchestrator/references/multi-session-compute.md
```
