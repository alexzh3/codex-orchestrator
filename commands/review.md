---
description: Review Codex output, run or inspect verification, and record evidence before accepting changes.
---

# Review

Use this command to review Codex output before accepting it.

Use when: Codex has produced a diff, artifact, report, or completed turn that needs evidence-based
acceptance review.

Do not use when: Claude and Codex disagree about a suspected bug or fix direction. Use
`/codex-orchestrator:consensus` for that resolution step.

Scope: review and evidence recording. This command assumes a run ledger already exists; create one
first with `/codex-orchestrator:start-run` or use `/codex-orchestrator:workflow` for the full run.

Checklist:

```bash
git diff
git status --short
python3 -m unittest discover -s tests -v
python3 scripts/codex_orch.py add-verification --run-id <run-id> --kind test --command "python3 -m unittest discover -s tests -v" --exit-code 0 --result passed --summary "Unit tests passed"
python3 scripts/codex_orch_append_event.py .codex-orchestrator/runs/<run-id> '{"type":"review"}'
```

Append the running review to the `## Review` section in `.codex-orchestrator/runs/<run-id>/report.md` and follow `skills/codex-orchestrator/SKILL.md` section 4.
