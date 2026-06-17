---
description: Inspect a Codex IDE or CLI session using compact status and tail reads instead of full log loading.
---

# Monitor

Use this command to inspect a Codex IDE or exec session without loading full rollout logs.

Use when: you have a `codex://threads/<thread-id>` URL or a captured `codex exec --json` stream and
need to know whether Codex is active, idle, complete, failed, or blocked on approval.

Do not use when: you need acceptance review or verification evidence. Use `/codex-orchestrator:review`
after monitoring shows the Codex turn is ready to inspect.

Default path:

```bash
python3 scripts/codex_orch_parse.py find <thread-id> --source ide --json
python3 scripts/codex_orch_parse.py state <thread-id> --source ide --json
python3 scripts/codex_orch_parse.py tail <thread-id> --source ide --since-offset <offset> --json
```

For headless exec streams, pass the captured `codex exec --json` stream:

```bash
python3 scripts/codex_orch_parse.py state <thread-id> --source exec --file <exec-jsonl> --json
```

Use `skills/codex-orchestrator/SKILL.md` sections 1-3 and 6 for the full monitoring rules.
