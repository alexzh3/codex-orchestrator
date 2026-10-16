---
name: codex-orchestrator-duet
description: Ask Claude and GPT (through Codex) the same prompt and return one aggregated answer.
argument-hint: <prompt>
---

# Duet

Send the user's prompt to both Claude (this session) and GPT (a fresh, read-only Codex session),
then return one aggregated answer.

Write the prompt verbatim to `<dir>/prompt.md` in a new temporary directory. If it relies on this
conversation, append the context Codex needs to answer on its own. Then launch Codex with Bash
`run_in_background: true` and `description` set to `codex-duet`:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/codex_orch_tools.py" run \
  --label codex-duet \
  --events "<dir>/events.jsonl" \
  --prompt "<dir>/prompt.md" \
  -- codex exec -C <working-directory> -s read-only -c approval_policy=never \
     --skip-git-repo-check --json --output-last-message "<dir>/codex.md" -
```

While it runs, write your own answer before opening `codex.md`. When Codex finishes, merge both
answers into one: combine what they share, resolve differences from evidence rather than by which
model said it, and briefly note any difference that stays open. If Codex failed, give your answer
and say so.
