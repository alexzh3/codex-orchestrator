# Start Run

Use this command to create the durable run ledger before dispatching or supervising Codex.

Scope: setup only. This command should create the compact runtime files and stop; it should not run
tests, review diffs, resolve consensus, or generate the final report. Use
`/codex-orchestrator:workflow` for the full end-to-end workflow.

Default path:

```bash
python3 scripts/codex_orch.py init --repo . --run-id <run-id>
```

Then follow `skills/codex-orchestrator/SKILL.md` "Run ledger" and sections 1-3 for session discovery and monitoring.
