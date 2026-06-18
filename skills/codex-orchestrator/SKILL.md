---
name: codex-orchestrator
description: >-
  Orchestrates, monitors, reviews, and coordinates Codex exec subagents and IDE sessions from Claude Code. Use when the user wants Claude to dispatch scoped Codex exec workers, watch live Codex sessions, review results, or coordinate sequential or parallel Codex work without file or compute conflicts.
---

# Claude-Codex Orchestration

Claude is the planner, monitor, reviewer, consensus broker, and compute gate. Codex is the scoped
executor or peer reviewer running in its native IDE or CLI harness.

A live IDE session is identified by a pasted `codex://threads/<thread-uuid>` URL. Headless sessions
started with `codex exec` are source kind `exec`; they are resumable from the CLI but do not appear
in the IDE sidebar. Start in the IDE when the user needs IDE visibility.

Default to an exec-first orchestration pattern for new work: Claude scopes one or more prompts,
reuses matching Codex agents when possible, launches Codex with `codex exec --json` only when a new
agent is needed, captures each JSONL stream under the run directory, and monitors the streams with
`codex_orch_parse.py state` and `tail`. Use IDE session monitoring when the user provides an
existing thread URL or explicitly needs sidebar visibility.

## When To Involve Codex

The "reuse before spawning" rules in this skill decide whether to start a *new* Codex agent versus
reuse an existing one. They do not decide whether to use Codex at all. Do not collapse to solo Claude
work just because a task looks small or review-shaped. Map the task to an action first:

- Implementation, repair, refactor, or test-writing: dispatch a Codex exec executor. This is Codex's
  job, not work to do solo.
- Review, verification, or "is this ready" gating: run Claude's own review first, then run an
  independent `codex exec review` pass on the diff as a required second opinion before acceptance.
- Pure ledger setup (`/codex-orchestrator:start-run`): no Codex; open the ledger and stop.

Solo Claude acceptance with no Codex pass is the exception, allowed only when the user explicitly
opts out. Record the opt-out and its reason as a ledger event.

## Commands

- `/codex-orchestrator:workflow`: full run that initializes or reuses a ledger, reuses or resumes
  existing Codex agents before dispatching new ones, monitors JSONL/IDE event streams, reviews and
  verifies the result, resolves consensus when needed, and writes the report. Also use this command
  with a scoped prompt for internal phases such as monitoring, review, handoff, consensus, or compute
  gating.
- `/codex-orchestrator:start-run`: open a run ledger only; create `state.json`, `ledger.jsonl`, and
  `report.md`, then stop.
- `/codex-orchestrator:report`: generate or update `report.md` from recorded evidence.

Monitoring, review, consensus, handoff, and compute gating are workflow phases, not separate slash
commands. Use `workflow` for active orchestration. Use `start-run` only to begin a tracked run and
continue manually.

## Durable Ledger

Use a durable run ledger for all orchestration state:

```text
.codex-orchestrator/runs/<run-id>/
  state.json    # compact mutable run/session state
  ledger.jsonl  # append-only events, verification, task updates, consensus records
  report.md     # human-readable review, consensus, and final report sections
```

Open the ledger; this is all `start-run` should do:

```bash
python3 scripts/codex_orch.py init --repo <repo> --run-id <run-id>
```

Later workflow/report helpers:

```bash
python3 scripts/codex_orch.py status --run-id <run-id>
python3 scripts/codex_orch.py append-event --run-id <run-id> '{"type":"note"}'
python3 scripts/codex_orch.py add-verification --run-id <run-id> --kind test --command "<cmd>" --exit-code <n> --result passed --summary "<summary>"
python3 scripts/codex_orch.py report --run-id <run-id>
```

Keep durable facts in these files, not only in model context. Update `state.json` when run or session
status changes, append material facts to `ledger.jsonl`, and keep `report.md` readable for the user.
Runtime records follow `schemas/codex-orchestrator.schema.json`.

## Workflow

1. Create or reuse a run id and initialize the durable ledger if missing.
2. Inspect `state.json` and recent ledger events for existing named Codex agents before starting any
   new session.
3. Break the user goal into scoped tasks. Dispatch the implementation, repair, refactor, or
   test-writing work to a Codex exec agent; this is Codex's job, not work to do solo. Use one
   reusable exec agent by default and several only when work can be isolated by worktree, files, or
   compute.
4. Resume the matching idle/complete Codex agent when the task continues its role, files, worktree,
   or prior context. Launch a new `codex exec --json` session only when the task is genuinely new,
   the old context is full or irrelevant, isolation requires it, or the user explicitly asks.
5. Attach to an IDE session when visibility or existing IDE context requires it.
6. Monitor each subagent using parser `state`/`tail` commands; store offsets/status in durable
   notes and never load full rollout logs.
7. Review code, diffs, logs, manifests, generated artifacts, and test output yourself.
8. Obtain an independent Codex review of the diff before acceptance (`codex exec review`), not only
   when Claude already suspects a problem. Solo Claude acceptance is allowed only with an explicit,
   recorded user opt-out.
9. Record verification evidence, including the Codex review, in `ledger.jsonl` and running notes in
   `report.md`.
10. If Claude and Codex disagree, resolve it with evidence and record the resolution as consensus
    before implementing or accepting the fix.
11. Generate or update `report.md` for handoff or approval.

Do not run this sequence for `/codex-orchestrator:start-run`; that command only opens the ledger.

## Agent Identity And Reuse

Treat each Codex session as a named agent with durable identity: role, thread id, worktree, branch,
event source, and current status. Reuse the same agent for follow-up prompts that belong to the same
task, files, subsystem, or review thread. Do not start a duplicate agent just because another prompt
is needed.

Before launching Codex:

1. Run `python3 scripts/codex_orch.py status --run-id <run-id>` or inspect `state.json`.
2. Classify each candidate session with `codex_orch_parse.py state`.
3. If a matching session is active, keep monitoring it.
4. If a matching session is idle or complete, resume it with the next scoped prompt.
5. If no matching session exists, create a new named agent and record why.

Start a new Codex session only when the work is unrelated to existing agents, the prior context is
full/stale/irrelevant for the next task, parser confidence is too low to trust the session after
bounded inspection, isolation requires a separate worktree, or the user explicitly requests a fresh
agent. Record the reason as a ledger event.

For IDE rollout sessions, keep using the same `codex://threads/<thread-uuid>` for follow-up work.
After a resume, re-find the newest rollout file for that thread id because Codex may append a new
file for the same session. A new rollout file is not by itself a new agent.

## Exec Subagents

Prefer exec subagents for new implementation, repair, and peer-review loops because they are cheap
to scope, resumable, and easy to monitor from compact JSONL. Treat them as persistent agents, not
one-shot commands. Give each subagent a bounded prompt, clear ownership, expected verification, and
a stop condition. Do not let multiple subagents edit the same files unless the workflow explicitly
serializes their handoff.

Capture each exec stream:

```bash
EXEC_LOG=".codex-orchestrator/runs/<run-id>/exec-<name>.jsonl"
"$CODEX" exec --json -s workspace-write -c approval_policy=never -C <worktree> "<scoped prompt>" > "$EXEC_LOG" & PID=$!
```

Record the subagent name, mode `exec`, worktree, branch, event file, and current status as ledger
events; keep `state.json` to compact session state. If the thread id is not known at launch, monitor
with a temporary name until the stream emits `thread.started`, then update the session record. Use
`codex exec resume <thread-uuid>` only when the previous turn is idle or complete.

## Monitoring Codex

Inside Claude Code, prefer native Monitor or Bash `run_in_background` over a manual sleep-poll loop.
Arm once and get woken on real events instead of burning a turn per poll. Parser `state` and `tail`
commands are the interpretation and fallback layer underneath the trigger, not a replacement for it.

Tier 1: for exec completion, use one Bash `run_in_background` notification. No Monitor tool is
needed. Launch and `wait` in the *same* command so `$PID` is a child you can `wait` on and capture
its exit code (a separate watcher shell cannot; there, persist the PID and poll `kill -0`). Report
the child rc with the final parser state so a crash or bad `$CODEX` path is not misread as idle:

```bash
# one run_in_background command: launch, block until real exit, then report status
"$CODEX" exec --json -s workspace-write -c approval_policy=never -C <worktree> "<prompt>" > "$EXEC_LOG" & PID=$!
wait "$PID"; RC=$?   # rc!=0, or an empty/unterminated log, means the run failed — not idle
python3 scripts/codex_orch_parse.py state <name> --source exec --file "$EXEC_LOG" --json
if [ "$RC" -ne 0 ]; then echo "EXEC EXITED rc=$RC — treat empty/partial log as failed"; fi
exit "$RC"   # wrapper exit code must mirror the child, not the last test (avoids the && status trap)
```

Tier 2: for progress, stall, or failure during a run, use the Monitor tool with the parser as the
filter, not text grep. Use a bounded `timeout_ms` for exec monitors and `persistent: true` for IDE
monitors:

```bash
LEDGER=.codex-orchestrator/runs/<run>/ledger.jsonl; STALE=600
# resume from the persisted offset for this (agent, log file); first arm falls back to 0 so a fast terminal event is not skipped
OFF=$(tac "$LEDGER" 2>/dev/null | jq -rc --arg f "$EXEC_LOG" 'select(.type=="monitor_offset" and .name=="<name>" and .file==$f).offset' | head -1)
OFF=${OFF:-0}; SZ=$(stat -c %s "$EXEC_LOG" 2>/dev/null || echo 0); (( OFF > SZ )) && OFF=0   # fresh/truncated log -> restart at 0
while true; do
  OUT=$(python3 scripts/codex_orch_parse.py tail <name> --source exec --file "$EXEC_LOG" --since-offset "$OFF" --json)
  OFF=$(jq -r '.next_offset' <<<"$OUT")
  # structured event types — no false positives from Codex merely *discussing* a commit
  # turn.completed/turn.failed always; error only when it is not a benign reconnect notice
  jq -rc '.events[]? | select((.type|test("turn.completed|turn.failed")) or (.type=="error" and ((.message//"")|test("[Rr]econnect")|not))) | "EVENT \(.type) \(.item.text // .message // "")"' <<<"$OUT"
  MT=$(stat -c %Y "$EXEC_LOG"); (( $(date +%s)-MT > STALE )) && { echo "STALL ${STALE}s — turn ended / awaiting approval"; break; }
  python3 scripts/codex_orch.py append-event --run-id <run> "{\"type\":\"monitor_offset\",\"name\":\"<name>\",\"file\":\"$EXEC_LOG\",\"offset\":$OFF}" >/dev/null  # persist per-(agent,file); MUST silence stdout
  sleep 90
done
```

In a Monitor, stdout is the event stream. Redirect `append-event` to `/dev/null` or every persist
call becomes a spurious notification. Cover failure signatures, not just success; silence is not
completion. Cap emitted events and use TaskStop before re-arming.

Tier 3: for IDE rollout sessions, resolve the newest rollout path with
`codex_orch_parse.py find <thread-uuid>` inside each monitor tick instead of caching the path. Codex
appends a new rollout file on resume.

Use bare parser commands as the fallback and interpretation layer:

```bash
python3 scripts/codex_orch_parse.py find <thread-uuid> --source ide --json
python3 scripts/codex_orch_parse.py state <thread-uuid> --source ide --json
python3 scripts/codex_orch_parse.py tail <thread-uuid> --source ide --since-offset <offset> --json
python3 scripts/codex_orch_parse.py state <thread-uuid> --source exec --file <exec-jsonl> --json
python3 scripts/codex_orch_parse.py tail <thread-uuid> --source exec --file <exec-jsonl> --since-offset <offset> --json
```

For exec monitors, use the `next_offset` returned by `state` or `tail` as the next
`--since-offset`. If parser confidence is low, run `--dump-event-types` and inspect a bounded raw
tail before trusting status.

Rollout path form: `~/.codex/sessions/YYYY/MM/DD/rollout-<ISO-ts>-<thread-uuid>.jsonl`. The date
is the session start day. Re-find after every resume because the same thread may append a new file.
Do not start a fresh IDE or exec thread for continuation work when a matching thread can be resumed.

Completion signals: `thread_goal_updated.status != active`, stale rollout mtime around 10+ minutes,
or self-started `codex exec` process exit. `codex app-server` liveness is not activity. If stale
mid-goal and narration asks for Docker, network, outside-sandbox, or similar approval, ask the user
to approve in VS Code/Cursor and watch for file growth.

Never load full rollout logs. Use parser state/tail, bounded raw tails, or `--dump-event-types` when
status confidence is low.

## Codex Exec

Locate the binary; IDE extension paths change:

```bash
CODEX=$(find ~/.cursor/extensions ~/.vscode/extensions ~/.vscode-server/extensions -maxdepth 4 -name codex -type f 2>/dev/null | head -1)
```

Default headless executor mode:

```bash
"$CODEX" exec -s workspace-write -c approval_policy=never "<prompt>"
"$CODEX" exec resume <thread-uuid> "<prompt>"
cat prompt.md | "$CODEX" exec -s workspace-write -c approval_policy=never
```

Resume only when idle or complete. Never use `--ephemeral`; history is required for audit and
resume. Start in the IDE when the user needs IDE sidebar visibility; headless exec sessions do not
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

## Review And Consensus

Treat code, diffs, tests, logs, manifests, and generated artifacts as source of truth. Treat agent
narration as intent until verified. Watch for failure spirals: weakened assertions, deleted inputs,
shrunk ranges, or special-cased validation failures.

For deterministic changes, inspect diffs and run relevant tests, typecheck, lint, build, or manifest
assertions. For nondeterministic rollout/training changes, require seeded determinism where possible,
metric thresholds, and regression bands; do not accept one stochastic pass.

Use a consensus-gated review loop:

1. Codex implements the scoped change.
2. Claude reviews the actual diff, tests, logs, manifests, and artifacts.
3. If Claude finds a suspected issue, share the exact finding, evidence, and proposed resolution
   with Codex before implementing or accepting a fix.
4. Record consensus: whether Claude and Codex agree, disagree, or partially agree; root cause when
   known; chosen fix or no-fix rationale; and the verification required.
5. Implement accepted fixes, then run Claude's final review and a Codex final review.
6. Accept only when both final reviews pass, or when the user explicitly accepts a recorded risk.

Run `codex exec review --uncommitted` (or `--commit <sha>` / `--base <branch>`) as the standard Codex
final review before acceptance. Do not accept on Claude's solo judgment unless the user explicitly
opts out, and record that opt-out.

When Claude needs Codex consensus on a finding, use a targeted prompt rather than another broad
rereview:

```bash
"$CODEX" exec resume <thread-id> "<specific finding, evidence, and proposed fix>"
```

Do not chain broad rereviews. If a final review still finds incorrect behavior after consensus fixes,
run one scoped rereview/fix loop for the unresolved issue and record why the extra pass was needed.
Escalate to the user instead of continuing open-ended review rounds.

Record suspected issue, root cause when known, agreed resolution, and verification as `consensus`
evidence in both `ledger.jsonl` and the `## Consensus` section of `report.md`.

## Multi-Session And Compute

Use separate worktrees for parallel sessions unless the user explicitly chooses same-worktree
coordination:

```bash
python3 scripts/codex_orch.py worktree --name codex-a
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

## Non-Negotiable Rules

- Treat artifacts as source of truth and narration as intent until verified.
- Never load whole rollout logs.
- Do not infer success from silence or low-confidence parser output.
- Re-find the rollout after every resume.
- Do not race a live Codex turn; resume or inject only when idle or complete.
- Reuse the matching named Codex agent before starting a new session.
- Never use `--ephemeral`.
- Default headless exec mode is `workspace-write` with `approval_policy=never`.
- Use separate worktrees for parallel Codex sessions unless the user chooses otherwise.
- Gate scarce compute before handoff.
- Do not accept a change on Claude's solo judgment; get an independent Codex review of the diff
  before acceptance unless the user explicitly opts out, and record the opt-out.
- Record consensus decisions and verification evidence durably.
