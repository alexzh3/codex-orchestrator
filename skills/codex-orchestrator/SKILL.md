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

## Progressive Disclosure

Keep this file in context as the operating contract. Do not open every reference by default. Open
only the reference that matches the current command or problem:

- `references/run-ledger.md`: runtime files, ledger CLI, verification records, report generation.
- `references/live-session-monitoring.md`: rollout discovery, compact state reads, tailing, idle and
  approval detection.
- `references/codex-exec.md`: locating the Codex binary, `codex exec`, resume, sandbox/approval
  modes, peer review.
- `references/review-consensus.md`: acceptance review, evidence rules, nondeterministic checks,
  consensus protocol.
- `references/multi-session-compute.md`: worktrees, parallel vs sequential coordination, handoff
  gates, GPU/Docker/Isaac checks.

## Slash Commands

- `/codex-orchestrator:workflow`: full run from setup through monitoring, review, verification,
  consensus when needed, and report.
- `/codex-orchestrator:start-run`: open a run ledger only; create `state.json`, `ledger.jsonl`, and
  `report.md`, then stop.
- `/codex-orchestrator:monitor`: inspect IDE or exec session state without loading full logs.
- `/codex-orchestrator:review`: review Codex output and record verification evidence.
- `/codex-orchestrator:consensus`: resolve a suspected bug or disagreement with Codex.
- `/codex-orchestrator:report`: generate or update `report.md` from recorded evidence.
- `/codex-orchestrator:handoff`: prepare a scoped Codex handoff or resume.
- `/codex-orchestrator:gate-compute`: check shared GPU, Docker, Isaac, Kit, and artifact resources.

Use `workflow` when Claude should coordinate the whole run end to end. Use `start-run` only when the
user wants to begin a tracked run and continue manually.

## Runtime Contract

Use a durable run ledger for all orchestration state:

```text
.codex-orchestrator/runs/<run-id>/
  state.json    # compact mutable run/session state
  ledger.jsonl  # append-only events, verification, task updates, consensus records
  report.md     # human-readable review, consensus, and final report sections
```

Opening a run ledger requires only:

```bash
python3 scripts/codex_orch.py init --repo <repo> --run-id <run-id>
```

Later workflow, review, consensus, or report commands may inspect status, append events, record
verification, and generate the report:

```bash
python3 scripts/codex_orch.py status --run-id <run-id>
python3 scripts/codex_orch_append_event.py .codex-orchestrator/runs/<run-id> '{"type":"note"}'
python3 scripts/codex_orch.py add-verification --run-id <run-id> --kind test --command "<cmd>" --exit-code 0 --result passed --summary "<what passed>"
python3 scripts/codex_orch.py report --run-id <run-id>
```

## End-To-End Workflow

1. Create or reuse a run id and initialize the durable ledger if missing.
2. Locate, start, or resume the relevant Codex session.
3. Monitor using parser/state/tail commands; never load full rollout logs.
4. Review code, diffs, logs, manifests, generated artifacts, and test output before acceptance.
5. Record verification evidence in `ledger.jsonl` and running notes in `report.md`.
6. If Claude finds a suspected issue, share it with Codex and record the evidence-based resolution
   as consensus before implementing or accepting the fix.
7. Generate or update `report.md` for handoff or approval.

Run this sequence for `/codex-orchestrator:workflow`, or manually through the step commands. Do not
run these steps for `/codex-orchestrator:start-run`; that command only opens the ledger.

## Non-Negotiable Rules

- Treat code, diffs, tests, logs, manifests, and generated artifacts as source of truth. Treat agent
  narration as intent until verified.
- Read Codex rollout logs through `scripts/codex_orch_parse.py` or bounded tails. Rollouts can be
  large; never load the whole file into context.
- If parser confidence is low or session status is ambiguous, inspect event types or bounded raw
  tails before acting. Do not infer success from silence.
- Re-find the rollout after every `codex exec resume`; the thread id is stable but a new file may be
  appended for the resumed turn.
- Do not race a live Codex turn. Resume or inject a prompt only when the session is idle or complete.
- Preserve session history. Never use `--ephemeral`; resumability and audit logs are part of the
  workflow.
- Use `codex exec -s workspace-write -c approval_policy=never` as the default headless executor
  mode. Use broad access only with explicit user authorization for that session.
- Use separate git worktrees for parallel Codex sessions unless the user explicitly chooses
  same-worktree coordination.
- Gate scarce compute before handoff and whenever unsure whether GPU, Docker, Isaac, Kit, training,
  or disk-heavy artifact generation is still busy.
- Record suspected mistakes, root cause when known, agreed resolution, and verification evidence in
  both `ledger.jsonl` and the `## Consensus` section of `report.md`.

## Session Source Split

IDE sessions use rollout JSONL tailing because `codex exec --json` is not available there:

```bash
python3 scripts/codex_orch_parse.py find <thread-uuid> --source ide --json
python3 scripts/codex_orch_parse.py state <thread-uuid> --source ide --json
python3 scripts/codex_orch_parse.py tail <thread-uuid> --source ide --since-offset <offset> --json
```

Headless exec sessions should capture the documented JSON stream and parse that file:

```bash
python3 scripts/codex_orch_parse.py state <thread-uuid> --source exec --file <exec-jsonl> --json
python3 scripts/codex_orch_parse.py tail <thread-uuid> --source exec --file <exec-jsonl> --since-offset <offset> --json
```

Use `--dump-event-types` when parse confidence is low or the event shape changed.
