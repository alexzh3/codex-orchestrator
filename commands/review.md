# Review

Use this command to review Codex output before accepting it.

Checklist:

```bash
git diff
git status --short
pytest -q
python scripts/codex_orch_append_event.py .codex-orchestrator/runs/<run-id> '{"type":"review"}'
```

Append the running review to `.codex-orchestrator/runs/<run-id>/review.md` and follow `skills/codex-orchestrator/SKILL.md` section 4.
