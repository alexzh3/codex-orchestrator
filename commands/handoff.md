# Handoff

Use this command to prepare a safe handoff to another Codex session.

For parallel work, create a separate worktree first:

```bash
python3 scripts/codex_orch_worktree.py --name codex-a
```

Then resume or start Codex with a scoped prompt:

```bash
"$CODEX" exec -s workspace-write -c approval_policy=never "<prompt>"
"$CODEX" exec resume <thread-id> "<prompt>"
```

Use `skills/codex-orchestrator/SKILL.md` section 5 for execution and the multi-session subsection for worktree and handoff rules.
