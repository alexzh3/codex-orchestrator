# Live Session Monitoring Reference

Use this when supervising a Codex IDE session or reading a captured headless `codex exec --json`
stream.

## Locate The Rollout

For IDE sessions, the user provides `codex://threads/<thread-uuid>`. Locate the newest rollout:

```bash
python3 scripts/codex_orch_parse.py find <thread-uuid> --source ide --json
```

Fallback:

```bash
find ~/.codex/sessions -name "*<thread-uuid>*" -printf '%T@ %p\n' 2>/dev/null | sort -n | tail -1
```

Path form: `~/.codex/sessions/YYYY/MM/DD/rollout-<ISO-ts>-<thread-uuid>.jsonl`. The date is the
session start day, not necessarily today. After every resume, re-find the rollout and take the newest
mtime; do not cache the old path.

## Read Compact State

Default parser calls:

```bash
python3 scripts/codex_orch_parse.py state <thread-uuid> --source ide --json
python3 scripts/codex_orch_parse.py state <thread-uuid> --source exec --file <exec-jsonl> --json
```

Useful event types include `message`, `agent_message`, `function_call`, `function_call_output`,
`thread_goal_updated`, and `token_count`. Use `--dump-event-types` if status confidence is low.

Goal-mode sessions emit `thread_goal_updated`; `payload.goal.status == active` means the goal is
running, and any other status means that goal ended. `codex app-server` process liveness is not a
completion signal because it lives as long as the IDE runs.

## Tail Without Loading Full Logs

Use bounded parser tails:

```bash
python3 scripts/codex_orch_parse.py tail <thread-uuid> --source ide --since-offset "$OFF" --json
python3 scripts/codex_orch_parse.py tail <thread-uuid> --source exec --file <exec-jsonl> --since-offset "$OFF" --json
```

Fallback latest-narration reader:

```bash
python3 - "$ROLLOUT" <<'EOF'
import json, os, sys, time
F=sys.argv[1]; sz=os.path.getsize(F); msgs=[]
with open(F) as f:
    f.seek(max(0, sz-500_000)); f.readline()
    for line in f:
        try: d=json.loads(line)
        except Exception: continue
        p=d.get("payload", {}) or {}
        if (p.get("type") or d.get("type")) == "agent_message":
            x=p.get("message") or p.get("text") or ""
            if isinstance(x, str) and x.strip(): msgs.append(x)
print("idle_min:", int((time.time()-os.stat(F).st_mtime)/60))
for m in msgs[-5:]: print("-", m[:300].replace("\n", " "))
EOF
```

## Completion And Blocked Signals

Use this priority order:

1. `thread_goal_updated.status != active`: the goal finished or was edited.
2. Rollout mtime stale for roughly 10+ minutes while status is still `active`: the turn ended, the
   session is idle, or it is awaiting an IDE approval.
3. A self-started `codex exec` launched in the background notifies on process exit; prefer that over
   polling for completion.

If the rollout goes idle mid-goal and the last narration says Codex needs outside-sandbox access,
Docker, network, or another approval, tell the user to approve in VS Code/Cursor and watch for the
file to grow again.

## Monitor Rules

Arm one monitor that emits only on events you would act on, then keep working. Avoid sleep/poll loops
in the chat. When writing a monitor, detect commits by comparing `git rev-parse HEAD`, detect value
changes from actual file contents, include failure signatures such as `FAILED ` and
`Traceback (most recent`, and cap emitted events so a noisy filter cannot flood the run.
