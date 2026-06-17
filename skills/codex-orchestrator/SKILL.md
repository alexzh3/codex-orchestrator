---
name: codex-orchestrator
description: >-
  Orchestrate, monitor, review, and coordinate Codex IDE or CLI sessions from
  Claude Code. Use when the user wants Claude to watch, review, drive, or
  coordinate Codex sessions sequentially or in parallel without file or compute
  conflicts.
---

# Claude-Codex Orchestration

Claude is the planner, monitor, reviewer, consensus broker, and compute gate. Codex is the scoped
executor or peer reviewer running in its native IDE or CLI harness.

A live IDE session is identified by a pasted `codex://threads/<thread-uuid>` URL. Headless sessions
started with `codex exec` are source kind `exec`; they are resumable from the CLI but do not appear
in the IDE sidebar. Start in the IDE when the user needs IDE visibility.

## Commands

- `/codex-orchestrator:workflow`: full run from setup through monitoring, review, verification,
  consensus when needed, and report. Also use this command with a scoped prompt for internal phases
  such as monitoring, review, handoff, consensus, or compute gating.
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

## Workflow

1. Create or reuse a run id and initialize the durable ledger if missing.
2. Locate, start, or resume the relevant Codex session.
3. Monitor using parser state/tail commands; never load full rollout logs.
4. Review code, diffs, logs, manifests, generated artifacts, and test output before acceptance.
5. Record verification evidence in `ledger.jsonl` and running notes in `report.md`.
6. If Claude finds a suspected issue, share it with Codex and record the evidence-based resolution
   as consensus before implementing or accepting the fix.
7. Generate or update `report.md` for handoff or approval.

Do not run this sequence for `/codex-orchestrator:start-run`; that command only opens the ledger.

## Monitoring Codex

IDE sessions use `codex://threads/<thread-uuid>` and rollout JSONL. Exec sessions use captured
`codex exec --json` streams.

```bash
python3 scripts/codex_orch_parse.py find <thread-uuid> --source ide --json
python3 scripts/codex_orch_parse.py state <thread-uuid> --source ide --json
python3 scripts/codex_orch_parse.py tail <thread-uuid> --source ide --since-offset <offset> --json
python3 scripts/codex_orch_parse.py state <thread-uuid> --source exec --file <exec-jsonl> --json
python3 scripts/codex_orch_parse.py tail <thread-uuid> --source exec --file <exec-jsonl> --since-offset <offset> --json
```

Rollout path form: `~/.codex/sessions/YYYY/MM/DD/rollout-<ISO-ts>-<thread-uuid>.jsonl`. The date
is the session start day. Re-find after every resume because the same thread may append a new file.

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

When Claude finds a suspected Codex mistake, share the exact finding and evidence back before
accepting or implementing:

```bash
"$CODEX" exec review --uncommitted
"$CODEX" exec resume <thread-id> "<specific finding, evidence, and proposed fix>"
```

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
- Never use `--ephemeral`.
- Default headless exec mode is `workspace-write` with `approval_policy=never`.
- Use separate worktrees for parallel Codex sessions unless the user chooses otherwise.
- Gate scarce compute before handoff.
- Record consensus decisions and verification evidence durably.
