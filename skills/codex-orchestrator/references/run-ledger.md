# Run Ledger Reference

Use this when initializing a run, recording events or verification evidence, or generating the final
report.

## Runtime Files

Runtime state lives under `.codex-orchestrator/runs/<run-id>/` and is ignored by git:

```text
state.json    # compact mutable state for run/session/review status
ledger.jsonl  # append-only event, verification, task update, and consensus records
report.md     # human-readable review, consensus, and final report sections
```

Keep durable facts in the files, not only in model context. Update `state.json` when run or session
status changes, append material facts to `ledger.jsonl`, and keep `report.md` readable for the user.

## Open A Ledger

Initialize from the target repository:

```bash
python3 scripts/codex_orch.py init --repo <repo> --run-id <run-id>
```

This is all `/codex-orchestrator:start-run` should do.

## Later Lifecycle CLI

Inspect compact status:

```bash
python3 scripts/codex_orch.py status --run-id <run-id>
```

Record verification evidence:

```bash
python3 scripts/codex_orch.py add-verification --run-id <run-id> --kind test --command "<test command>" --exit-code 0 --result passed --summary "<what passed>"
```

Generate or refresh the human-readable report:

```bash
python3 scripts/codex_orch.py report --run-id <run-id>
```

Append material events:

```bash
python3 scripts/codex_orch_append_event.py .codex-orchestrator/runs/<run-id> '{"type":"note"}'
```

## Report Policy

`report.md` should summarize accepted changes, verification evidence, unresolved risks, and every
recorded consensus decision. It should not be the only source of machine-readable facts; keep the
structured evidence in `ledger.jsonl`.

`start-run` is setup-only. It creates the runtime files and stops. It does not run tests, review
diffs, resolve consensus, or generate the final report. `workflow` continues through monitoring,
review, verification, consensus, and report generation.
