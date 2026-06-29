# Agent Identity, Handoff, And Compute

## Agent Identity And Reuse

Treat each Codex session as a named agent with durable identity: role, thread id, worktree, branch,
event source, and current status. Session reuse is simple: continue in the same Codex session when
its context is relevant to the task; if it is almost full but still relevant, compact/summarize the
relevant state and continue there; create a new Codex session only for contextually unrelated work,
required isolation, or an explicit user request. Do not start a duplicate agent just because another
prompt is needed.

When compacting a relevant Codex session before continuing, preserve: goal, files touched, key
decisions, current diff/test status, unresolved issues, and the next scoped prompt.

Before launching Codex:

1. Run `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/codex_orch.py" status --run-id <run-id>` or inspect
   `state.json`.
2. Classify each candidate session with `${CLAUDE_PLUGIN_ROOT}/scripts/codex_orch_parse.py state`.
3. If a matching session is active, keep monitoring it.
4. If a matching session is idle or complete, resume it with the next scoped prompt.
5. If no matching session exists, create a new named agent and record why.

Start a new Codex session only when the work is contextually unrelated to existing agents, parser
confidence is too low to trust the session after bounded inspection, isolation requires a separate
worktree, or the user explicitly requests a fresh agent. An almost-full but relevant session is a
compaction/resume case, not a new-session reason. Record the reason as a ledger event.

For IDE rollout sessions, keep using the same `codex://threads/<thread-uuid>` for follow-up work.
After a resume, re-find the newest rollout file for that thread id because Codex may append a new
file for the same session. A new rollout file is not by itself a new agent.

## Multi-Session And Compute

Use separate worktrees for parallel sessions unless the user explicitly chooses same-worktree
coordination:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/codex_orch.py" worktree --name codex-a
```

Use sequential handoff when agents touch the same files/contracts or share scarce compute/artifact
paths. Before handoff: finish review, verify the next plan, gate compute, send a scoped prompt, and
re-arm monitoring.

Compute checks:

```bash
nvidia-smi --query-gpu=memory.used,memory.total,utilization.gpu --format=csv,noheader
nvidia-smi --query-compute-apps=pid,used_memory --format=csv,noheader
pgrep -af 'isaac|kit|python.sh|pytest' | grep -v codex
docker ps --format '{{.Names}} {{.Status}}'
free -g
df -h /
```

`docker ps` showing `Up` is not proof of activity; check VRAM, utilization, compute apps, and disk.
