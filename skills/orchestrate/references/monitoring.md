# Monitoring And Codex Sessions

Use the bundled parser for compact status and deltas. Do not load an entire event stream unless a
bounded inspection cannot explain an ambiguous or failed session.

## Headless Codex

For each prompt/execution/handoff cycle, create the next numbered execution directly under its named
agent:

```text
agents/codex-impl-01/execution-01/
  prompt.md
  events.jsonl
  handoff.md
```

Save `prompt.md`, then append the ledger `execution` before launch. Capture raw stdout as the event
stream and the native last message as the handoff:

```bash
EXECUTION_DIR=".codex-orchestrator/runs/<run-id>/agents/codex-impl-01/execution-01"
"$CODEX" exec --json --output-last-message "$EXECUTION_DIR/handoff.md" \
  -s workspace-write -c approval_policy=never -C <worktree> \
  - \
  < "$EXECUTION_DIR/prompt.md" \
  > "$EXECUTION_DIR/events.jsonl"
```

Never use `--ephemeral`, because session history is needed for resumption and audit. Use broad
access only with explicit user authorization and an appropriately isolated environment.

Require Codex to end every execution with this concise handoff shape:

```markdown
## Status

## Summary

## Files Changed

## Claims / Findings

## Commands Reported

## Caveats / Blockers
```

`--output-last-message` is the normal capture path. Parser extraction of the last completed agent
message is a fallback for older or interrupted runs, not a reason to mine logs during normal review.

Resume a relevant, idle session as another captured execution under the same named agent:

```bash
"$CODEX" exec resume --json \
  --output-last-message "$EXECUTION_DIR/handoff.md" \
  <session-id> - \
  < "$EXECUTION_DIR/prompt.md" \
  > "$EXECUTION_DIR/events.jsonl"
```

The resumed execution records the same native `session_id`. Starting a fresh native session creates
a new named agent.

## IDE Sessions

A live IDE session is identified by `codex://threads/<thread-uuid>`. When Claude attaches only to
observe a session that is already active, append an execution with `mode: "observe"`,
`event_source: "ide"`, the native `session_id`, the absolute rollout path in `events`, and a local
`handoff` path. Omit `prompt` because Claude sent no prompt; this is the only missing-prompt case
allowed by the journal contract. Do not copy the rollout into the run directory. Save the exact
final agent message locally as `handoff.md`.

If Claude later sends a follow-up, create the next normal prompted execution under the same agent:
save its exact `prompt.md`, record its paths before sending it, and capture its final response as the
new handoff.

Resolve the current rollout path rather than assuming an old path remains active:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/codex_orch_parse.py" find <thread-uuid> --source ide --json
```

The usual rollout path is:

```text
~/.codex/sessions/YYYY/MM/DD/rollout-<ISO-ts>-<thread-uuid>.jsonl
```

Re-find it after resumption because the same native session can append through a new rollout file.

## Parser And Monitor

Use parser state and tail offsets instead of raw grep:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/codex_orch_parse.py" state <session-id> --source exec --file <events-jsonl> --json
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/codex_orch_parse.py" tail <session-id> --source exec --file <events-jsonl> --since-offset <offset> --json
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/codex_orch_parse.py" state <session-id> --source ide --file <rollout-jsonl> --json
```

Persist no parser offset in the ledger. Callers retain `next_offset` while monitoring and can
restart from zero after context loss because the parser returns compact output.

The bundled run monitor treats a `run_started` record without a later `run_closed` as Claude's
active-run marker, then watches executions without recorded terminal execution results:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/bin/codex-orch-monitor" --repo <repo> --run-id <run-id>
python3 "${CLAUDE_PLUGIN_ROOT}/bin/codex-orch-monitor" --log <events-jsonl> --fail-on-session-failure
```

It emits compact completion, failure, and stale notifications and never writes the ledger. These
markers support discovery but do not independently prove lifecycle state. Explicit paths may point
to local headless streams or external IDE rollouts. Use bounded raw tails only when parser
confidence is low.

Completion signals include a terminal parser state or the self-started `codex exec` process exit.
Silence is not completion. A stale stream may mean the session ended, blocked, or is awaiting an
approval; inspect bounded context before deciding. Append the terminal `execution_result` only after
Claude has inspected the handoff and repository state.
