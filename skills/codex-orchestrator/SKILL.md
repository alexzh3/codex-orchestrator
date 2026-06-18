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

Default to an exec-first orchestration pattern for new work: once a plan exists, Codex is the first
mover for implementation, repair, refactor, and test-writing. Claude scopes prompts, reuses matching
Codex agents when possible, launches Codex with `codex exec --json` only when a new agent is needed,
captures each JSONL stream under the run directory, and monitors the streams with
`codex_orch_parse.py state` and `tail`. Use IDE session monitoring when the user provides an
existing thread URL or explicitly needs sidebar visibility.

## When To Involve Codex

The "reuse before spawning" rules in this skill decide whether to start a *new* Codex agent versus
reuse an existing one. They do not decide whether to use Codex at all. Do not collapse to solo Claude
work just because a task looks small or review-shaped. Map the task to an action first:

- Implementation, repair, refactor, or test-writing: dispatch or resume a Codex exec executor first
  once the task has a usable plan. This is Codex's job, not work to do solo before Codex has moved.
- Review, verification, or "is this ready" gating: run Claude's own review first, then run an
  independent `codex exec review` pass on the diff as a required second opinion before acceptance.
- Pure ledger setup (`/codex-orchestrator:start-run`): no Codex; open the ledger and stop.

Claude may plan before dispatch only when no plan exists, the scope is ambiguous, or safety/compute
gating is needed. That plan is an orchestration plan for Codex executors: choose task boundaries,
agent reuse, worktrees, verification gates, and handoff order with Codex subagents in mind. Planning
does not authorize solo Claude execution; after planning, delegate the scoped work to Codex and
orchestrate it.

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
python3 scripts/codex_orch.py add-verification --run-id <run-id> --kind test --command "<cmd>" --exit-code <n> --result passed --summary "<summary>"
python3 scripts/codex_orch.py report --run-id <run-id>
```

Use `append-event` only as an advanced escape hatch for custom material facts that do not yet have a
typed command:

```bash
python3 scripts/codex_orch.py append-event --run-id <run-id> '{"type":"note"}'
```

Keep durable facts in these files, not only in model context. Keep `state.json` as a compact
run/session snapshot where relevant, append material facts to `ledger.jsonl`, and keep `report.md`
readable for the user. Runtime records follow `schemas/codex-orchestrator.schema.json`.

## Workflow

1. Create or reuse a run id and initialize the durable ledger if missing.
2. Inspect `state.json` and recent ledger events for existing named Codex agents before starting any
   new session.
3. If no usable plan exists, create or validate a minimal orchestration plan that assumes Codex
   subagent executors are available: choose task boundaries, reuse strategy, worktree isolation, and
   verification gates. Once the plan is usable, make Codex the first mover for implementation,
   repair, refactor, or test-writing: dispatch or resume a Codex exec agent before Claude implements
   or reviews the work. Use one reusable exec agent by default and several only when work can be
   isolated by worktree, files, or compute.
4. Continue in the same Codex session when that session's context is relevant to the next task. If
   it is almost full but still contextually relevant, compact/summarize the relevant state, then
   continue the same session. Launch a new `codex exec --json` session only when the task is
   contextually unrelated to existing sessions, isolation requires it, or the user explicitly asks.
5. Attach to an IDE session when visibility or existing IDE context requires it.
6. Monitor during Codex execution. Do not edit overlapping implementation files while a Codex
   executor owns them; wait until Codex yields, completes, or a serialized handoff is recorded.
7. After Codex yields or completes, review artifacts and run the consensus-gated review loop below.
8. Record verification evidence, consensus decisions, and final report state durably.
9. Generate or update `report.md` for handoff or approval.

Do not run this sequence for `/codex-orchestrator:start-run`; that command only opens the ledger.

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

1. Run `python3 scripts/codex_orch.py status --run-id <run-id>` or inspect `state.json`.
2. Classify each candidate session with `codex_orch_parse.py state`.
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
Native monitoring wakes Claude; `codex_orch_parse.py` interprets JSONL; `state.json`/`ledger.jsonl`
persist durable facts. For concrete native Monitor and `run_in_background` recipes, read
`references/monitoring.md`.

Core monitoring rules:

- Use parser `state`/`tail` output, not raw grep, to interpret Codex JSONL.
- Use `next_offset` to read deltas and avoid reloading full rollout logs.
- Cover failure signals, not only success; silence is not completion.
- Re-find IDE rollout paths after every resume.
- In a Monitor, stdout is the event stream; silence bookkeeping commands such as `append-event`.

Bare parser commands:

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
- Planning is for delegation: design the work around Codex executors, then delegate. Once a usable
  plan exists, Codex is the first mover for implementation, repair, refactor, and test-writing;
  Claude monitors during execution and reviews/edits only after Codex yields or completes.
- Do not edit files owned by an active Codex executor unless a serialized handoff explicitly transfers
  ownership.
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
- Do not chain broad rereviews. After final review, run at most one scoped rereview/fix loop for a
  real unresolved issue, then escalate to the user.
- Record consensus decisions and verification evidence durably.
