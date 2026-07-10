---
name: codex-orchestrator-report
description: Author the final report from a completed, gated, and validated orchestration ledger.
---

# Report

Use this skill only after the orchestration run is finished. Do not start agents, continue task
work, or generate an interim report here. Use `${CLAUDE_PLUGIN_ROOT}/skills/orchestrate/SKILL.md`
for focused orchestration and `${CLAUDE_PLUGIN_ROOT}/skills/workflow/SKILL.md` for the end-to-end
workflow.

## Preconditions

Run `gate` and `doctor` before authoring the report:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/codex_orch.py" gate --run-id <run-id>
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/codex_orch.py" doctor --run-id <run-id>
```

The gate may pass or remain blocked because of an explicitly recorded unresolved outcome. In either
case, do not write the report until the latest `gate_result` exists, doctor findings have been
reviewed, all tasks are terminal, the run is closed, and no further run work is planned. Never edit
the ledger merely to make the report look complete.

Read the complete run context under `.codex-orchestrator/runs/<run-id>/`:

```text
state.json
ledger.jsonl
prompts/
logs/
artifacts/
report.md
```

Also inspect the final repository diff and relevant verification artifacts. Treat `ledger.jsonl` as
the primary source of truth and use other sources only to clarify recorded facts. Do not invent or
silently repair missing evidence.

## Required Report Structure

Replace the contents of `report.md` with a complete Claude-authored report using exactly these five
top-level sections in this order:

```markdown
# Report

## Summary

## Changes

## Orchestration Graph

## Consensus

## Final Results
```

Do not add other `##` sections.

### Summary

State the original goal, the overall result, the final acceptance state, and the most important
reason for that outcome. Mention unresolved work without burying it. Keep this section concise.

### Changes

Describe material delivered changes and their owning task or worker. Cite important files and
artifacts when useful. Distinguish completed, blocked, failed, and intentionally unchanged work.
Do not turn the section into a raw ledger dump.

### Orchestration Graph

Create `## Orchestration Graph` as a readable Mermaid `flowchart TD`.

Use `ledger.jsonl` as the primary source, supplemented only when needed by run context, state, logs,
artifacts, and repository changes. Do not invent facts.

Use this consistent top-to-bottom structure:

1. `A_CLAUDE{{"Claude Code<br/>planner · orchestrator"}}`
2. Separate non-empty subgraphs for dispatched Claude workers and Codex sessions.
3. Important reviews, verifications, direct checks, consensus records, and decisions.
4. Material tasks and produced deliverables.
5. The latest acceptance gate, meaningful fix or recheck loops, and the final recorded state.

Create one node per distinct execution context. Use a recorded thread or session identifier when
available. A resumed session remains the same node; create another node only when a fresh worker or
session is recorded. Order execution nodes by their first dispatch.

Session and worker labels should include their role, model and effort when recorded, main result,
and terminal status. Represent substantial tasks or deliverables as separate nodes connected to
their producer instead of crowding them into the session label.

Use concise action labels such as `dispatch`, `review`, `verified`, `supports`,
`tie-break evidence`, `consensus`, `claude_decision`, `produced`, `fix required`, `recheck`, and
`accepted`.

Show only evidence that materially affected a decision, retry, or gate. Combine routine passing
checks when they have the same subject and outcome. Group numerous related decisions by topic or
deliverable, while keeping `claude_decision`, user decisions, and unresolved outcomes distinct.

Treat consensus `evidence_refs` as supporting evidence. Use `clears` only when the corresponding
record explicitly identifies what was cleared. Do not imply that supporting evidence resolved a
finding.

Prefer recorded facts. When a useful association can only be reconstructed from corroborating
state, logs, artifacts, or repository changes, label that node or edge `inferred`. Never infer a
review result, verification result, decision outcome, gate result, or terminal status.

Prioritize a clear causal overview over reproducing every ledger event. Omit empty categories and
incidental activity.

### Consensus

Summarize material reviews, disagreements, and decisions. For each consequential resolution,
include its outcome and basis, what it clears when explicitly recorded, and the supporting evidence.
Keep `claude_decision`, user decisions, accepted risks, and unresolved outcomes distinct. Say
clearly when no consensus decision was required.

### Final Results

Use these subsections in this order:

```markdown
### Gate Result

### Risks / Follow-ups
```

Under `Gate Result`, report the latest recorded gate status, blocking reasons, and warnings. Do not
recompute or soften the gate result. Under `Risks / Follow-ups`, list unresolved verification,
blocked or failed work, user actions, accepted risks, and concrete next steps. Write `None recorded.`
when there are no remaining risks or follow-ups.

At the end of Final Results, include recorded Claude Code and Codex CLI versions in one compact
`Run metadata` bullet. Omit unavailable values, protocol version, and schema version. Do not add a
separate Reproducibility section.

## Final Check

Before handoff, reread the finished report and verify that the five required `##` sections appear
once and in order, the Mermaid block parses visually, every material claim is grounded in recorded
evidence, and Final Results matches the latest `gate_result`.

Reference: `${CLAUDE_PLUGIN_ROOT}/skills/orchestrate/SKILL.md`.
