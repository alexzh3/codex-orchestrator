# Monitoring And Codex Sessions

Use parser output and recorded evidence as the source of truth. Agent narration is intent until
verified.

A live IDE session is identified by a pasted `codex://threads/<thread-uuid>` URL. Headless sessions
started with `codex exec` are source kind `exec`; they are resumable from the CLI but do not appear
in the IDE sidebar. Start in the IDE when the user needs IDE visibility.

## Headless Codex Agents

Prefer headless Codex agents for new implementation, repair, and peer-review loops because they are
cheap to scope, resumable, and easy to monitor from compact JSONL. Treat them as persistent agents,
not one-shot commands. Give each agent a bounded prompt, clear ownership, expected verification, and
a stop condition. Do not let multiple agents edit the same files unless the workflow explicitly
serializes their handoff.

Capture each headless Codex stream:

```bash
RUN_DIR=".codex-orchestrator/runs/<run-id>"
PROMPT_FILE="$RUN_DIR/prompts/exec-<name>.md"
EXEC_LOG="$RUN_DIR/logs/exec-<name>.jsonl"
"$CODEX" exec --json -s workspace-write -c approval_policy=never -C <worktree> < "$PROMPT_FILE" > "$EXEC_LOG" & PID=$!
```

Record the agent name, mode `exec`, worktree, branch, event file, and current status as ledger
events; include the prompt and log paths when available. Keep `state.json` to compact session state.
If the thread id is not known at launch, monitor with a temporary name until the stream emits
`thread.started`, then update the session record. Use `codex exec resume <thread-uuid>` only when
the previous turn is idle or complete.

## Codex CLI Invocation

Locate the binary; IDE extension paths change:

```bash
CODEX=$(find ~/.cursor/extensions ~/.vscode/extensions ~/.vscode-server/extensions -maxdepth 4 -name codex -type f 2>/dev/null | head -1)
```

Default headless Codex command:

```bash
"$CODEX" exec -s workspace-write -c approval_policy=never "<prompt>"
"$CODEX" exec resume <thread-uuid> "<prompt>"
cat prompt.md | "$CODEX" exec -s workspace-write -c approval_policy=never
```

Resume only when idle or complete. Never use `--ephemeral`; history is required for audit and
resume. Start in the IDE when the user needs IDE sidebar visibility; headless Codex sessions do not
appear there.

Use broad access only with explicit user authorization:

```bash
"$CODEX" exec --dangerously-bypass-approvals-and-sandbox "<prompt>"
```

Peer review:

```bash
"$CODEX" exec review --uncommitted
"$CODEX" exec review --base <branch>
"$CODEX" exec review --commit <sha>
```

## Monitoring Codex

Inside Claude Code, prefer native Monitor or Bash `run_in_background` over a manual sleep-poll loop.
Native monitoring wakes Claude; `${CLAUDE_PLUGIN_ROOT}/scripts/codex_orch_parse.py` interprets JSONL;
`state.json`/`ledger.jsonl` persist durable facts.

Core monitoring rules:

- Use parser `state`/`tail` output, not raw grep, to interpret Codex JSONL.
- Use `next_offset` to read deltas and avoid reloading full rollout logs.
- Cover failure signals, not only success; silence is not completion.
- Re-find IDE rollout paths after every resume.
- In a Monitor, stdout is the event stream; silence bookkeeping commands such as `append-event`.

Bare parser commands:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/codex_orch_parse.py" find <thread-uuid> --source ide --json
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/codex_orch_parse.py" state <thread-uuid> --source ide --json
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/codex_orch_parse.py" tail <thread-uuid> --source ide --since-offset <offset> --json
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/codex_orch_parse.py" state <thread-uuid> --source exec --file <exec-jsonl> --json
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/codex_orch_parse.py" tail <thread-uuid> --source exec --file <exec-jsonl> --since-offset <offset> --json
```

For exec monitors, use the `next_offset` returned by `state` or `tail` as the next
`--since-offset`. If parser confidence is low, run `--dump-event-types` and inspect a bounded raw
tail before trusting status.

Rollout path form:

```text
~/.codex/sessions/YYYY/MM/DD/rollout-<ISO-ts>-<thread-uuid>.jsonl
```

The date is the session start day. Re-find after every resume because the same thread may append a
new file. Do not start a fresh IDE or exec thread for continuation work when a matching thread can
be resumed.

Completion signals: `thread_goal_updated.status != active`, stale rollout mtime around 10+ minutes,
or self-started `codex exec` process exit. `codex app-server` liveness is not activity. If stale
mid-goal and narration asks for Docker, network, outside-sandbox, or similar approval, ask the user
to approve in VS Code/Cursor and watch for file growth.

Never load full rollout logs. Use parser state/tail, bounded raw tails, or `--dump-event-types` when
status confidence is low.

## Native Monitoring Recipes

Use these recipes only when running inside Claude Code and you need concrete native Monitor or
`run_in_background` commands. The core rule is:

```text
Claude Code native Monitor / run_in_background = wake-up trigger
${CLAUDE_PLUGIN_ROOT}/scripts/codex_orch_parse.py = JSONL interpretation
state.json / ledger.jsonl                      = durable state and evidence
prompts/ and logs/                             = paired prompt and JSONL files by stem
```

Do not treat these shell snippets as the source of truth. Parser output and recorded evidence are
the source of truth.

### Bundled Run Monitor

The plugin bundles `${CLAUDE_PLUGIN_ROOT}/bin/codex-orch-monitor` as a ready-made native-Monitor
command. Launch it on demand during this monitoring phase; the plugin does not auto-start it on
enable. Scope it to the active run and Claude wakes on each emitted event:

```bash
# native Monitor command: watch the active run's newest captured log(s)
python3 "${CLAUDE_PLUGIN_ROOT}/bin/codex-orch-monitor" --run-id <run-id> --repo <repo>
# or watch one specific captured stream and exit nonzero if that session fails
python3 "${CLAUDE_PLUGIN_ROOT}/bin/codex-orch-monitor" --log "$EXEC_LOG" --fail-on-session-failure
```

Its stdout is the event stream: it emits compact `codex_session_complete`, `codex_session_failed`,
and `codex_session_stale` events, does not mutate the ledger, and exits once every watched log is
complete, failed, or stale. Always scope it to `--run-id` or `--log`; the no-arg auto-discovery mode
is a long-lived poll loop meant for manual use, not for arming inside a run.

### Exec Completion

For exec completion, use one Bash `run_in_background` notification. Launch and `wait` in the same
command so `$PID` is a child you can wait on and capture its exit code. A separate watcher shell
cannot `wait` on a PID it did not spawn; if launched separately, persist the PID and poll `kill -0`.

```bash
# one run_in_background command: launch, block until real exit, then report status
RUN_DIR=.codex-orchestrator/runs/<run>
PROMPT_FILE="$RUN_DIR/prompts/<name>.md"
EXEC_LOG="$RUN_DIR/logs/<name>.jsonl"
"$CODEX" exec --json -s workspace-write -c approval_policy=never -C <worktree> < "$PROMPT_FILE" > "$EXEC_LOG" & PID=$!
wait "$PID"; RC=$?   # rc!=0, or an empty/unterminated log, means the run failed, not idle
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/codex_orch_parse.py" state <name> --source exec --file "$EXEC_LOG" --json
if [ "$RC" -ne 0 ]; then echo "EXEC EXITED rc=$RC - treat empty/partial log as failed"; fi
exit "$RC"
```

The wrapper exit code must mirror the child. Avoid ending with a test such as
`[ "$RC" -ne 0 ] && echo ...`, because that can invert success and failure.

### Progress, Stall, And Failure

For progress, stall, or failure during a run, use the Monitor tool with the parser as the filter,
not raw text grep. Use a bounded `timeout_ms` for exec monitors and `persistent: true` for IDE
monitors.

```bash
LEDGER=.codex-orchestrator/runs/<run>/ledger.jsonl; STALE=600
# resume from the persisted offset for this (agent, log file); first arm falls back to 0 so a fast terminal event is not skipped
OFF=$(tac "$LEDGER" 2>/dev/null | jq -rc --arg f "$EXEC_LOG" 'select(.type=="monitor_offset" and .name=="<name>" and .file==$f).offset' | head -1)
OFF=${OFF:-0}; SZ=$(stat -c %s "$EXEC_LOG" 2>/dev/null || echo 0); (( OFF > SZ )) && OFF=0
while true; do
  OUT=$(python3 "${CLAUDE_PLUGIN_ROOT}/scripts/codex_orch_parse.py" tail <name> --source exec --file "$EXEC_LOG" --since-offset "$OFF" --json)
  OFF=$(jq -r '.next_offset' <<<"$OUT")
  # turn.completed/turn.failed always; error only when it is not a benign reconnect notice
  jq -rc '.events[]? | select((.type|test("turn.completed|turn.failed")) or (.type=="error" and ((.message//"")|test("[Rr]econnect")|not))) | "EVENT \(.type) \(.item.text // .message // "")"' <<<"$OUT"
  MT=$(stat -c %Y "$EXEC_LOG"); (( $(date +%s)-MT > STALE )) && { echo "STALL ${STALE}s - turn ended / awaiting approval"; break; }
  python3 "${CLAUDE_PLUGIN_ROOT}/scripts/codex_orch.py" append-event --run-id <run> "{\"type\":\"monitor_offset\",\"name\":\"<name>\",\"file\":\"$EXEC_LOG\",\"offset\":$OFF}" >/dev/null
  sleep 90
done
```

In a Monitor, stdout is the event stream. Redirect `append-event` to `/dev/null` or every persist
call becomes a spurious notification. Cover failure signatures, not just success; silence is not
completion. Cap emitted events and use TaskStop before re-arming.

### IDE Rollout Sessions

For IDE rollout sessions, resolve the newest rollout path with
`${CLAUDE_PLUGIN_ROOT}/scripts/codex_orch_parse.py find <thread-uuid>` inside each monitor tick
instead of caching the path. Codex may append a new rollout file on resume.
