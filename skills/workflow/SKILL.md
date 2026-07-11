---
name: codex-orchestrator-workflow
description: Run the full Codex orchestration workflow end to end.
---

# Workflow

Use this skill for one complete run. Follow the protocol in
`${CLAUDE_PLUGIN_ROOT}/skills/orchestrate/SKILL.md` from planning through terminal tasks; do not
redefine or skip its execution, review, verification, or decision rules.

When the work is finished:

1. Re-read the full journal and inspect the final repository state and diff.
2. Run the descriptive close check:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/codex_orch_tools.py" validate \
  .codex-orchestrator/runs/<run-id>
```

3. Resolve structural issues and inspect every non-passing verification. Append one final
   `run_closed` entry with `judgment: passed|blocked`, the exact validation result, unresolved risks,
   and follow-ups. Validation detects omissions; Claude decides acceptance.
4. After `run_closed`, invoke `${CLAUDE_PLUGIN_ROOT}/skills/report/SKILL.md` to create `report.md`
   once.

The canonical close sequence is `validate → run_closed → report.md`. Validation never decides
acceptance, and the final report never repairs or rewrites journal history.
