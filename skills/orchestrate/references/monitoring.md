# Monitoring And Codex Sessions

Use the bundled tools for compact status snapshots. They parse event streams locally; do not copy
raw logs into Claude's context unless a focused inspection is needed for an ambiguous or failed
session.

## Headless Codex

Create the next numbered execution under its named agent:

```text
codex-impl-01/execution-01/
  prompt.md
  events.jsonl
  handoff.md
```

Save `prompt.md` and append `execution` before launch. Capture stdout as `events.jsonl` and the last
message as `handoff.md`:

```bash
EXECUTION_DIR=".codex-orchestrator/runs/<run-id>/codex-impl-01/execution-01"
codex exec --json --output-last-message "$EXECUTION_DIR/handoff.md" \
  -s workspace-write -c approval_policy=never -C <worktree> \
  - \
  < "$EXECUTION_DIR/prompt.md" \
  > "$EXECUTION_DIR/events.jsonl"
```

Never use `--ephemeral`. Use broad access only with explicit authorization and isolation.

Require Codex to end every execution with this concise handoff shape:

```markdown
## Status

## Summary

## Files Changed

## Claims / Findings

## Commands Reported

## Caveats / Blockers
```

Extract the last completed agent message from events only when normal handoff capture failed.

Resume a relevant idle session as the next execution under the same agent:

```bash
codex exec -C <worktree> -s workspace-write -c approval_policy=never \
  resume --json \
  --output-last-message "$EXECUTION_DIR/handoff.md" \
  <session-id> - \
  < "$EXECUTION_DIR/prompt.md" \
  > "$EXECUTION_DIR/events.jsonl"
```

Use the original worktree with `-C`, the same `session_id`, and an absolute `EXECUTION_DIR` when the
shell runs elsewhere. A fresh native session requires a new named agent.

## IDE Sessions

For observe-only attachment to `codex://threads/<thread-uuid>`, record `mode: "observe"`,
`event_source: "ide"`, `session_id`, the absolute rollout path in `events`, and a local `handoff`.
Omit `prompt`, do not copy the rollout, and save the exact final message as `handoff.md`.

For a follow-up, create the next prompted execution under the same agent and capture its prompt,
paths, and handoff normally.

Resolve the rollout path on attachment and after resumption:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/codex_orch_tools.py" find <thread-uuid> --json
```

## Session State And Monitor

Use `state` for a compact session snapshot:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/codex_orch_tools.py" state <session-id> --source exec --file <events-jsonl> --json
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/codex_orch_tools.py" state <session-id> --source ide --file <rollout-jsonl> --json
```

After context loss, call `state` again. Do not persist parser positions in the journal.

Monitor an active run or explicit stream:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/codex_orch_tools.py" monitor \
  --repo <repo> --run-id <run-id>
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/codex_orch_tools.py" monitor \
  --log <events-jsonl> --fail-on-session-failure
```

The monitor is read-only and emits completion, failure, blocking, unknown-format, missing-stream,
or stale notifications. Treat silence and staleness as ambiguous; inspect the handoff and
repository before appending `execution_result`.
