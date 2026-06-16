---
name: codex-orchestrator
description: >-
  Orchestrate, monitor, review, and coordinate Codex IDE or CLI sessions from
  Claude Code. Use when the user wants Claude to watch, review, drive, or
  coordinate Codex sessions sequentially or in parallel without file or compute
  conflicts.
---

# Claude-Codex orchestration

The user runs **GPT Codex** (the IDE extension, such as VS Code or Cursor, package id
`openai.chatgpt-*`, app-server mode)
on coding/research goals and asks Claude Code to **watch, review, drive, or orchestrate** those
sessions. This skill is the playbook: locate a session, read its live state, monitor it, drive it
non-interactively, and run it as a headless executor — without burning tokens polling.

A live IDE-extension session is identified by a `codex://threads/<thread-uuid>` URL the user pastes;
everything below keys off that `<thread-uuid>`. A session you start yourself with `codex exec`
(no `resume`) creates a fresh thread instead.

## 1. Locate the session's rollout file

Codex writes a JSONL rollout (full event log) per session:

```bash
find ~/.codex/sessions -name "*<thread-uuid>*" -printf '%T@ %p\n' 2>/dev/null | sort -n | tail -1
```

- Path form: `~/.codex/sessions/YYYY/MM/DD/rollout-<ISO-ts>-<thread-uuid>.jsonl`.
- The date in the path is the session's **start** day, not today.
- **Resume/exec appends a NEW file** for the same thread id (see §5). Re-`find` and take the
  newest by mtime — don't cache the path across a resume.

## 2. Read session state (read-only, cheap)

Each line is a JSON event. Useful `payload.type` (or top-level `type`) values:
`message` (role user/assistant), `agent_message` (Codex's narration), `function_call` /
`function_call_output` (its tool calls + output), `thread_goal_updated`, `token_count`.

**Goal status** — goal-mode sessions emit `thread_goal_updated` whose `payload.goal.status` is
`active` while running; anything else (`complete`, …) means that goal ended:

```bash
python3 - "$ROLLOUT" <<'EOF'
import json,sys
last=None
for line in open(sys.argv[1]):
    try: d=json.loads(line)
    except: continue
    p=d.get('payload',d)
    if (p.get('type') or d.get('type'))=='thread_goal_updated':
        last=p.get('goal',{})
print("GOAL:", last.get('status') if last else "none", "|", (last or {}).get('text','')[:200])
EOF
```

**Latest narration** — seek the last ~500KB (these logs reach tens of MB; never read whole):

```bash
python3 - "$ROLLOUT" <<'EOF'
import json,os,sys,time
F=sys.argv[1]; sz=os.path.getsize(F); msgs=[]
with open(F) as f:
    f.seek(max(0,sz-500_000)); f.readline()      # skip partial line
    for line in f:
        try: d=json.loads(line)
        except: continue
        p=d.get('payload',{}) or {}
        if (p.get('type') or d.get('type'))=='agent_message':
            x=p.get('message') or p.get('text') or ''
            if isinstance(x,str) and x.strip(): msgs.append(x)
print("idle_min:", int((time.time()-os.stat(F).st_mtime)/60))
for m in msgs[-5:]: print('-', m[:300].replace('\n',' '))
EOF
```

**Completion / idle signals** (priority order):

1. `thread_goal_updated.status != active` → the goal finished or was edited.
2. Rollout mtime stale (≈10+ min) while status still `active` → turn ended; Codex is idle or
   **awaiting an IDE approval** (see §6).
3. `codex app-server` process liveness is **not** a completion signal — it lives as long as the IDE
   runs (`ps aux | grep '[c]odex app-server'`). A self-started `codex exec` you launched with
   Bash `run_in_background`, by contrast, notifies you on exit — prefer that over polling.

## 3. Monitor it (the Monitor tool, not polling)

Arm one Monitor that emits only on events you'd act on, then keep working — do not sleep/poll.
Hard-won rules:

- **Commit detection off `git rev-parse HEAD`, not text** — matching `"git commit"` in the log
  fires on Codex merely *discussing* one. Compare real HEAD per repo.
- **"Value changed" off actual file values**, not "file was edited" — Codex re-saves files with no
  net change; diff the parsed constants and embed the new state inline in the event.
- **Idle** via mtime staleness; **resume-after-idle** via the file growing again (often = the user
  approved an IDE prompt).
- Cover failure signatures (`FAILED `, `Traceback (most recent`), not just success — silence ≠ ok.
- Cap emitted events (`EMITS>=N; exit`) so a misbehaving filter can't flood the chat; re-arm after.
- Poll 90–120s; a self-started `codex exec` in Bash background already pings you on exit, so a
  Monitor there is only for **progress + stall** detection, not the exit itself.

Skeleton (adapt `state()`/grep to the task):

```bash
F=<rollout>; REPO=<repo>; OFF=$(stat -c%s "$F"); HEAD0=$(git -C "$REPO" rev-parse HEAD); EMITS=0
TMP=/tmp/codexmon.$$.txt
state(){ grep -E '<the constants you care about>' "$REPO/<file>" | tr -s ' \n' ' '; }
S0=$(state)
while true; do
  sleep 120
  NOW=$(date +%s); MT=$(stat -c %Y "$F"); SZ=$(stat -c%s "$F")
  (( NOW-MT > 600 )) && { echo "IDLE $(((NOW-MT)/60))min — turn ended / awaiting approval"; exit 0; }
  H=$(git -C "$REPO" rev-parse HEAD); [ "$H" != "$HEAD0" ] && { HEAD0=$H; EMITS=$((EMITS+1)); echo "COMMIT: $(git -C "$REPO" log --oneline -1)"; }
  S1=$(state); [ "$S1" != "$S0" ] && { S0=$S1; EMITS=$((EMITS+1)); echo "VALUE CHANGE: ${S1:0:600}"; }
  if (( SZ>OFF )); then tail -c +$((OFF+1)) "$F" >"$TMP"; OFF=$SZ
    grep -q thread_goal_updated "$TMP" && { echo "GOAL EVENT"; exit 0; }
    grep -qE 'FAILED |Traceback \(most recent' "$TMP" && { EMITS=$((EMITS+1)); echo "FAILURE in new output"; }
  fi
  (( EMITS>=10 )) && { echo "event cap — re-arm if needed"; exit 0; }
done
```

`persistent: true` for live IDE-extension sessions; bounded `timeout_ms` for a self-started exec. Stop with
TaskStop when done or before re-arming.

## 4. Review as coordinator

- Treat **code as source of truth**, narration as *intent*. Verify claims against the working tree /
  `git show` / generated manifests / test output — "it passes" is a claim until you read the JSON.
- Watch for **failure spirals**: answering every validation failure by shrinking ranges / deleting
  test inputs may be masking a root cause. Flag the *pattern*, not just the edit.
- Keep a timestamped running review in **memory** so the drift history survives compaction.
- You usually can't safely interrupt a live Codex turn. Spot a mistake mid-run → record it + give
  the user a paste-ready steer; only inject (§5) when the session is idle.

## 5. Drive / execute through a session (`codex exec`)

There is often **no `codex` on PATH**, but the IDE extension ships the binary (version dir changes
across updates — locate it, don't hardcode). Search common Cursor and VS Code extension locations:

```bash
CODEX=$(
  find ~/.cursor/extensions ~/.vscode/extensions ~/.vscode-server/extensions \
    -maxdepth 4 -name codex -type f 2>/dev/null | head -1
)
"$CODEX" exec [OPTIONS] "<prompt>"                  # fresh thread (new task)
"$CODEX" exec resume <thread-uuid> "<prompt>"       # continue an existing thread's context
"$CODEX" exec resume --last "<prompt>"              # continue the most recent session
```

- `resume` replays the thread's context, then runs your prompt as the next turn. Only resume when
  the session is **idle** (mtime stale) — don't race a live turn. Each run appends a new rollout
  (re-`find`, §1).
- Long prompts: pass via **stdin** (`cat prompt.md | "$CODEX" exec ...`) to dodge shell-escaping; a
  piped stdin alongside a prompt arg is appended as a `<stdin>` block.
- **Always preserve history. Never use `--ephemeral`** in this workflow. Stored session/rollout
  history is required so the same thread/agent can be resumed when context matters and so the user
  has durable logs for audit, debugging, and thesis/research handoff.
- **Visibility:** If the user wants the session visible in the Codex IDE sidebar, start it in the IDE
  and pass Claude the `codex://threads/<thread-uuid>` URL. Use `codex exec` only for headless runs:
  those sessions use source kind `exec`, are CLI-resumable with
  `codex resume --all --include-non-interactive`, and do not appear in the IDE sidebar. Spoof session rollout metadata with `source: vscode` when the user explicitly asks for visibility, but warn them it might have future implications.

### Run modes (sandbox × approval) — verified

Headless `codex exec` has **no user to approve IDE escalation prompts**, so the run mode must be
chosen up front, not left to default. Two modes that actually work hands-off:

- **Executor mode (safe, default for code work):** `-s workspace-write -c approval_policy=never`.
  Codex edits files in the workspace and **never pauses** for approval; Docker, GPU, network, and
  out-of-workspace writes stay blocked. Pair it with the orchestrator (Claude) running all the
  heavy/unsafe steps — Docker/GPU tests, rollouts, commits. This is the **Codex-as-executor /
  Claude-as-orchestrator** split and needs no dangerous access.
- **Autonomous mode (only when Codex itself must run Docker/commit/network):**
  `--dangerously-bypass-approvals-and-sandbox` (or `-s danger-full-access`) — self-described as
  EXTREMELY DANGEROUS (full host access, autonomous writes + commits). Use only with explicit,
  durable user authorization for that session. Without it, a restrictive sandbox makes a headless
  exec **stall or fail** at the first escape (Docker socket, git write outside workspace).

`approval_policy` accepts `untrusted | on-failure | on-request | never`; `never` = don't escalate,
just run sandboxed and adapt (no stall). Alternative to autonomous mode: the user keeps the session
open in the IDE and approves escalations there while you coordinate.

### Useful flags / config (verified, codex-cli 0.140)

- Model + effort: `-m <model>` or `-c model="gpt-5.5"`; `-c model_reasoning_effort="xhigh"`
  (`low|medium|high|xhigh`); `-c service_tier="priority"`. Defaults load from `~/.codex/config.toml`
  (holds `model`, `model_reasoning_effort`, `service_tier`, per-project `trust_level`).
- `-C/--cd <dir>` working root · `--add-dir <dir>` extra writable root · `--skip-git-repo-check`.
- `-o/--output-last-message <file>` — capture Codex's final summary cleanly (great for handoffs).
- `--json` JSONL event stream · `-i/--image` attach images.
- Do not pass `--ephemeral`; it prevents durable session files and breaks resumability/logging.

### Peer review

`codex exec review` runs a code review against the repo:

```bash
"$CODEX" exec review --uncommitted        # staged + unstaged + untracked (a working-tree diff)
"$CODEX" exec review --base <branch>      # vs a base branch
"$CODEX" exec review --commit <sha>       # a single commit
```

Use `--uncommitted` to have Codex review changes (its own or yours) before commit.

### Multi-session coordination

Parallel Codex sessions are fine when their work scopes do not conflict and they do not compete for
scarce compute. Prefer parallel coordination for independent code/research tasks with separate
files, branches, artifacts, or output directories.

Use sequential coordination when a compute gate is needed (shared GPU, Isaac/Kit/training rollouts,
Docker-bound runs), when the user explicitly asks for serial handoff, or when agents would touch the
same files/contracts and could race each other.

When coordinating parallel sessions:

1. Assign non-overlapping goals, file scopes, and artifact/output directories.
2. Track each thread id and newest rollout path separately; do not mix monitor state across agents.
3. Verify each session's claims against code, manifests, and test output before accepting the work.
4. If shared compute or file conflicts appear, stop dispatching new parallel work and switch that
   subset to the sequential handoff below.

When sequential coordination is required:

1. Wait for the current goal to **complete** (§2) and finish your review.
2. **Verify the next session's plan** before triggering it — read its rollout, extract the concrete
   plan, sanity-check against the codebase. This is the user's explicit gate.
3. **Compute gate at the handoff** (§7): confirm no Isaac/training process survives the previous step.
4. Trigger via `codex exec resume` with a tightly-scoped go-ahead, then re-arm a monitor.

## 6. "Awaiting approval" detection

If the rollout goes idle mid-goal and the last `agent_message` says e.g. "I'll request … outside
the sandbox" / "needs Docker socket access", the session is **blocked on an IDE approval**, not
done. Tell the user to approve in VS Code/Cursor; watch for the file to grow again (resume-after-idle) and
pick your review back up.

## 7. Compute gating

Codex self-gates and **the coordinator should not run rollouts** — but gate at handoffs and whenever
unsure the GPU is free:

```bash
nvidia-smi --query-gpu=memory.used,memory.total,utilization.gpu --format=csv,noheader
nvidia-smi --query-compute-apps=pid,used_memory --format=csv,noheader
pgrep -af 'isaac|kit|python.sh|pytest' | grep -v codex
docker ps --format '{{.Names}} {{.Status}}'      # the Isaac container may be Up but idle
free -g; df -h /                                  # video/HDF5 artifacts fill disk
```

A container being "Up" ≠ busy: check VRAM/util + compute-apps. No compute-apps + low util = safe to
hand off. `run_docker.sh` is interactive (`--rm --tty`); for headless `docker exec` automation start
a detached container yourself.

## 8. Consensus protocol

When Claude (orchestrator) finds and debugs an error/mistake during review, **share it back with
Codex to reach consensus on the fix before implementing** — it may not actually be a mistake, or
Codex may have context Claude lacks. Mechanism: `codex exec review --uncommitted` to have Codex
critique the diff, or `codex exec resume <id> "<the specific finding + proposed fix>"` to discuss.
**Record each such mistake (what, root cause, agreed resolution) in the final report.**

## Gotchas

- Rollout files are large — always seek/tail, never read whole.
- The path date is the session **start** date; a 2-day-old session's file is under its start day.
- `app-server` liveness ≠ session activity; a self-started `exec` notifies on exit instead.
- Don't trust "passed" narration — open the manifest/JSON/test output.
- Re-find the rollout after every resume; the thread id is stable, the filename isn't.
- Never use `--ephemeral`; preserve session history for resumable context and logs.
