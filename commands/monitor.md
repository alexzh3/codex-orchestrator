# Monitor

Use this command to inspect a Codex IDE or exec session without loading full rollout logs.

Default path:

```bash
python scripts/codex_orch_parse.py find <thread-id> --source ide --json
python scripts/codex_orch_parse.py state <thread-id> --source ide --json
python scripts/codex_orch_parse.py tail <thread-id> --source ide --since-offset <offset> --json
```

For headless exec streams, pass the captured `codex exec --json` stream:

```bash
python scripts/codex_orch_parse.py state <thread-id> --source exec --file <exec-jsonl> --json
```

Use `skills/codex-orchestrator/SKILL.md` sections 1-3 and 6 for the full monitoring rules.
