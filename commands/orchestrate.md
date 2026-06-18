---
description: Orchestrates, monitors, reviews, and coordinates Codex agents and IDE sessions from Claude Code. Use when the user wants Claude to dispatch scoped Codex workers, watch live Codex sessions, review results, or coordinate sequential or parallel Codex work without file or compute conflicts.
---

# Claude-Codex Orchestration

Claude is the planner, monitor, reviewer, consensus broker, and compute gate. Codex is the scoped
implementation agent or peer reviewer running in its native IDE or CLI harness.

A live IDE session is identified by a pasted `codex://threads/<thread-uuid>` URL. Headless sessions
started with `codex exec` are source kind `exec`; they are resumable from the CLI but do not appear
in the IDE sidebar. Start in the IDE when the user needs IDE visibility.

Default to a Codex-first orchestration pattern for new work: once a plan exists, Codex is the first
mover for implementation, repair, refactor, and test-writing. Claude scopes prompts, reuses matching
Codex agents when possible, launches Codex with `codex exec --json` only when a new agent is needed,
captures each JSONL stream under the run directory, and monitors the streams with
`${CLAUDE_PLUGIN_ROOT}/scripts/codex_orch_parse.py state` and `tail`. Use IDE session monitoring
when the user provides an existing thread URL or explicitly needs sidebar visibility.

## When To Involve Codex

`orchestrate` is prompt-directed: use the user prompt and recorded run state as scope, and do not
create a full execution plan for focused monitoring, review, consensus, handoff, or compute-gating
phases. The reuse rules decide whether to resume an existing Codex agent or start a new one; they do
not authorize Claude to bypass Codex for implementation or review.

- Implementation, repair, refactor, or test-writing: dispatch or resume a Codex agent first.
  If scope is missing, create only the minimal dispatch plan: task boundary, agent reuse, file
  ownership/isolation, and verification gate.
- Review, verification, or "is this ready" gating: review artifacts yourself, then get an independent
  `codex exec review` pass before acceptance.
- Plan review: mandatory Codex review of new Claude-created plans belongs to
  `/codex-orchestrator:workflow`; in `orchestrate`, request it only when the user asks or risk
  warrants a second opinion.
- Ledger-only setup: run the internal init helper and stop.

## Command Boundary

Use `/codex-orchestrator:workflow` only for the full end-to-end run: ledger setup, planning,
dispatch, monitoring, review, verification, consensus, and report.

Use `/codex-orchestrator:report` only to regenerate `report.md` from recorded evidence.

Monitoring, review, consensus, handoff, and compute gating are workflow phases, not separate slash
commands.

## Durable Ledger

Use a durable run ledger for all orchestration state:

```text
.codex-orchestrator/runs/<run-id>/
  state.json    # compact mutable run/session state
  ledger.jsonl  # append-only events, verification, task updates, consensus records
  report.md     # authored Summary/Changes plus generated evidence, consensus, and risks
  prompts/      # exact prompts sent to Codex
  logs/         # captured headless Codex JSONL streams
  artifacts/    # generated files, manifests, screenshots, benchmark outputs
```

Slash commands initialize the ledger internally when orchestration starts. Manual init is only for
debugging or explicit ledger-only setup:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/codex_orch.py" init --repo <repo> --run-id <run-id>
```

Later workflow/report helpers:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/codex_orch.py" status --run-id <run-id>
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/codex_orch.py" add-verification --run-id <run-id> --kind test --command "<cmd>" --exit-code <n> --result passed --summary "<summary>"
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/codex_orch.py" report --run-id <run-id>
```

Use `append-event` only as an advanced escape hatch for custom material facts that do not yet have a
typed command. Known ledger event types are schema-validated; custom event types are recorded as
generic ledger events:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/codex_orch.py" append-event --run-id <run-id> '{"type":"note"}'
```

Keep durable facts in these files, not only in model context. Keep `state.json` as a compact
run/session snapshot where relevant, append material facts to `ledger.jsonl`, and keep `report.md`
readable for the user. Runtime records follow `schemas/codex-orchestrator.schema.json`.
In `report.md`, Claude should author the `Summary` and `Changes` sections after inspecting the diff,
ledger, prompts, logs, and verification. The report helper preserves those sections and regenerates
`Evidence`, `Consensus`, and `Risks / Follow-ups` from durable records.

Use matching stems for Codex prompts and logs. For example, write the exact final review prompt to
`prompts/final-review.md` and capture its JSONL stream in `logs/final-review.jsonl`. Do this for
plan reviews, implementation prompts, diff reviews, consensus prompts, rereviews, and handoffs. Keep the
ledger as the index by recording the prompt/log paths in the relevant session, verification, or
consensus event.

## Workflow

1. Create or reuse a run id and initialize the durable ledger if missing.
2. Inspect `state.json` and recent ledger events for existing named Codex agents before starting any
   new session.
3. For focused phases, use the prompt and recorded run state as the scope. If dispatching
   implementation work and no usable scope exists, create or validate a minimal dispatch plan for
   Codex agents: task boundaries, reuse strategy, worktree isolation, and verification gates.
4. For `/codex-orchestrator:workflow`, have Codex review any new Claude-created plan before
   execution. For `/codex-orchestrator:orchestrate`, do this only when requested or when the new plan
   is risky enough to require a second opinion before dispatch.
5. If Claude and Codex disagree about a reviewed plan, record the evidence and choose one outcome:
   `consensus` when evidence resolves the disagreement, `claude_decision` when Claude proceeds with
   recorded rationale/risk, or `user_action_required` when Claude is not confident enough to
   continue or accept without user input.
6. Once the scope is usable, make Codex the first mover for implementation, repair,
   refactor, or test-writing: dispatch or resume a Codex agent before Claude implements or
   reviews the work. Use one reusable Codex agent by default and several only when work can be isolated
   by worktree, files, or compute.
7. Continue in the same Codex session when that session's context is relevant to the next task. If
   it is almost full but still contextually relevant, compact/summarize the relevant state, then
   continue the same session. Launch a new `codex exec --json` session only when the task is
   contextually unrelated to existing sessions, isolation requires it, or the user explicitly asks.
8. Attach to an IDE session when visibility or existing IDE context requires it.
9. Monitor during Codex execution. Do not edit overlapping implementation files while a Codex agent
   owns them; wait until Codex yields, completes, or a serialized handoff is recorded.
10. After Codex yields or completes, review artifacts and run the consensus-gated review loop below.
11. Record verification evidence, consensus decisions, and final report state durably.
12. Generate or update `report.md` for handoff or approval.

If the user explicitly asks only to open a ledger, run the internal init helper and stop.

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

## Headless Codex Agents

Prefer headless Codex agents for new implementation, repair, and peer-review loops because they are cheap
to scope, resumable, and easy to monitor from compact JSONL. Treat them as persistent agents, not
one-shot commands. Give each agent a bounded prompt, clear ownership, expected verification, and
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

## Monitoring Codex

Inside Claude Code, prefer native Monitor or Bash `run_in_background` over a manual sleep-poll loop.
Native monitoring wakes Claude; `${CLAUDE_PLUGIN_ROOT}/scripts/codex_orch_parse.py` interprets JSONL;
`state.json`/`ledger.jsonl` persist durable facts. For concrete native Monitor and
`run_in_background` recipes, read `${CLAUDE_PLUGIN_ROOT}/references/monitoring.md`.

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

Rollout path form: `~/.codex/sessions/YYYY/MM/DD/rollout-<ISO-ts>-<thread-uuid>.jsonl`. The date
is the session start day. Re-find after every resume because the same thread may append a new file.
Do not start a fresh IDE or exec thread for continuation work when a matching thread can be resumed.

Completion signals: `thread_goal_updated.status != active`, stale rollout mtime around 10+ minutes,
or self-started `codex exec` process exit. `codex app-server` liveness is not activity. If stale
mid-goal and narration asks for Docker, network, outside-sandbox, or similar approval, ask the user
to approve in VS Code/Cursor and watch for file growth.

Never load full rollout logs. Use parser state/tail, bounded raw tails, or `--dump-event-types` when
status confidence is low.

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
4. Record the outcome: `consensus`, `claude_decision`, or `user_action_required`; whether Claude and
   Codex agree, disagree, or partially agree; root cause when known; chosen fix or no-fix rationale;
   risk level; whether user input is required; and the verification required.
5. Implement accepted fixes, then run Claude's final review and a Codex final review.
6. Accept when both final reviews pass or when Claude records `claude_decision` after the evidence
   review. Use `user_action_required` only when Claude needs user input before continuing or
   accepting.

Run `codex exec review --uncommitted` (or `--commit <sha>` / `--base <branch>`) as the standard Codex
final review before acceptance whenever a diff exists. A `claude_decision` outcome must still record
evidence, rationale, risk level, and verification.

Save every Codex review or consensus prompt under `prompts/` before running it, and capture its
JSONL output under `logs/` with the same filename stem. Reference both paths from the review or
consensus ledger record.

When Claude needs Codex consensus on a finding, use a targeted prompt rather than another broad
rereview:

```bash
"$CODEX" exec resume <thread-id> "<specific finding, evidence, and proposed fix>"
```

Do not chain broad rereviews. If a final review still finds incorrect behavior after consensus fixes,
run one scoped rereview/fix loop for the unresolved issue and record why the extra pass was needed.
Escalate to the user instead of continuing open-ended review rounds.

Record suspected issue, root cause when known, outcome, and verification as `consensus` evidence in
both `ledger.jsonl` and the `## Consensus` section of `report.md`.

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
