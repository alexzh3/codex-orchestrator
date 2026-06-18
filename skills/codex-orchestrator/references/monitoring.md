# Native Monitoring Recipes

Use these recipes only when running inside Claude Code and you need concrete native Monitor or
`run_in_background` commands. The core rule is:

```text
Claude Code native Monitor / run_in_background = wake-up trigger
codex_orch_parse.py                            = JSONL interpretation
state.json / ledger.jsonl                      = durable state and evidence
```

Do not treat these shell snippets as the source of truth. Parser output and recorded evidence are
the source of truth.

## Exec Completion

For exec completion, use one Bash `run_in_background` notification. Launch and `wait` in the same
command so `$PID` is a child you can wait on and capture its exit code. A separate watcher shell
cannot `wait` on a PID it did not spawn; if launched separately, persist the PID and poll `kill -0`.

```bash
# one run_in_background command: launch, block until real exit, then report status
"$CODEX" exec --json -s workspace-write -c approval_policy=never -C <worktree> "<prompt>" > "$EXEC_LOG" & PID=$!
wait "$PID"; RC=$?   # rc!=0, or an empty/unterminated log, means the run failed, not idle
python3 scripts/codex_orch_parse.py state <name> --source exec --file "$EXEC_LOG" --json
if [ "$RC" -ne 0 ]; then echo "EXEC EXITED rc=$RC - treat empty/partial log as failed"; fi
exit "$RC"
```

The wrapper exit code must mirror the child. Avoid ending with a test such as
`[ "$RC" -ne 0 ] && echo ...`, because that can invert success and failure.

## Progress, Stall, And Failure

For progress, stall, or failure during a run, use the Monitor tool with the parser as the filter,
not raw text grep. Use a bounded `timeout_ms` for exec monitors and `persistent: true` for IDE
monitors.

```bash
LEDGER=.codex-orchestrator/runs/<run>/ledger.jsonl; STALE=600
# resume from the persisted offset for this (agent, log file); first arm falls back to 0 so a fast terminal event is not skipped
OFF=$(tac "$LEDGER" 2>/dev/null | jq -rc --arg f "$EXEC_LOG" 'select(.type=="monitor_offset" and .name=="<name>" and .file==$f).offset' | head -1)
OFF=${OFF:-0}; SZ=$(stat -c %s "$EXEC_LOG" 2>/dev/null || echo 0); (( OFF > SZ )) && OFF=0
while true; do
  OUT=$(python3 scripts/codex_orch_parse.py tail <name> --source exec --file "$EXEC_LOG" --since-offset "$OFF" --json)
  OFF=$(jq -r '.next_offset' <<<"$OUT")
  # turn.completed/turn.failed always; error only when it is not a benign reconnect notice
  jq -rc '.events[]? | select((.type|test("turn.completed|turn.failed")) or (.type=="error" and ((.message//"")|test("[Rr]econnect")|not))) | "EVENT \(.type) \(.item.text // .message // "")"' <<<"$OUT"
  MT=$(stat -c %Y "$EXEC_LOG"); (( $(date +%s)-MT > STALE )) && { echo "STALL ${STALE}s - turn ended / awaiting approval"; break; }
  python3 scripts/codex_orch.py append-event --run-id <run> "{\"type\":\"monitor_offset\",\"name\":\"<name>\",\"file\":\"$EXEC_LOG\",\"offset\":$OFF}" >/dev/null
  sleep 90
done
```

In a Monitor, stdout is the event stream. Redirect `append-event` to `/dev/null` or every persist
call becomes a spurious notification. Cover failure signatures, not just success; silence is not
completion. Cap emitted events and use TaskStop before re-arming.

## IDE Rollout Sessions

For IDE rollout sessions, resolve the newest rollout path with
`codex_orch_parse.py find <thread-uuid>` inside each monitor tick instead of caching the path. Codex
may append a new rollout file on resume.

Rollout path form:

```text
~/.codex/sessions/YYYY/MM/DD/rollout-<ISO-ts>-<thread-uuid>.jsonl
```

The date is the session start day, not necessarily today.
