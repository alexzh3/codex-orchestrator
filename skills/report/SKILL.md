---
name: codex-orchestrator-report
description: Author the final report from a completed and structurally validated orchestration run.
---

# Report

Use this skill only after orchestration work has finished. Do not start agents, continue tasks, or
write an interim report here. Return to `${CLAUDE_PLUGIN_ROOT}/skills/orchestrate/SKILL.md` or
`${CLAUDE_PLUGIN_ROOT}/skills/workflow/SKILL.md` when more work is needed.

## Preconditions

The run must have followed this order:

```text
validate → run_closed → report.md
```

Confirm that:

- structural validation ran before closure and its complete result is recorded in
  `run_closed.validation`;
- every execution has a terminal execution result and every task is terminal;
- `run_closed` is the final ledger record and contains `judgment: passed|blocked`;
- no further run work is planned.

If these conditions are not true, stop and return to orchestration. Never edit the ledger merely to
make the report look complete.

Read the complete `ledger.jsonl` first. Then inspect relevant handoffs, evidence, the final
repository diff, and other run context needed to substantiate the report. Raw `events.jsonl` or
external IDE rollouts are fallback sources for disputes, ambiguity, or debugging; do not mine them
for facts already captured in handoffs or verification. Treat the ledger as the primary source and
do not invent or silently repair missing facts.

## Required Report Structure

Replace `report.md` with a complete Claude-authored report using exactly these five top-level
sections in this order:

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

State the original goal, overall result, `run_closed.judgment`, and the main reason for that outcome.
Mention unresolved work plainly and keep this section concise.

### Changes

Describe material delivered changes and their owning tasks or agents. Cite important repository
files and evidence when useful. Distinguish complete, blocked, failed, and intentionally unchanged
work. Do not reproduce the ledger line by line.

### Orchestration Graph

Create a readable Mermaid `flowchart TD`. Use `ledger.jsonl` as the primary source, supplemented by
handoffs, evidence, repository changes, and raw events only when necessary. Do not invent facts.

Use this top-to-bottom structure:

1. `A_CLAUDE{{"Claude Code<br/>planner · orchestrator"}}`
2. Separate non-empty subgraphs for assigned Claude agents and Codex agents.
3. Important reviews, verifications, direct checks, consensus, and decisions.
4. Produced deliverables.
5. Final judgment, meaningful fix/recheck loops, and final state.

Create one node per distinct agent or native session. Include its assigned task, model/effort when
recorded, main result, and terminal status. A resumed session remains one node even when it has
multiple executions. Order agents by first execution.

Label assignment edges `assign`; use other concise actions such as `review`, `verified`,
`tie-break evidence`, `consensus`, `claude_decision`, `produced`, `fix required`, `recheck`, and
`accepted`.

Show evidence only when it affected a decision or final judgment; combine routine passing checks.
Group numerous related decisions by topic or deliverable while keeping `claude_decision`, user
decisions, and unresolved outcomes distinct. Prioritize a clear causal overview over every ledger
event. Mark reconstructed information as `inferred`, and never infer a verification result,
decision outcome, judgment, or terminal status.

### Consensus

Summarize consequential reviews and `decision` records. State the outcome, basis, resolution, and
risk for each material disagreement. Keep consensus, Claude decisions, user actions, accepted risks,
and unresolved outcomes distinct. Say clearly when no decision record was required.

### Final Results

Use these subsections in this order:

```markdown
### Gate Result

### Risks / Follow-ups
```

Under `Gate Result`, report `run_closed.judgment`, its summary, and the recorded validation issues
and warnings. This is a human-facing heading, not a separate ledger event. Do not recompute or
soften Claude's recorded judgment.

Under `Risks / Follow-ups`, list unresolved checks, blocked or failed work, user actions, accepted
risks, and concrete next steps. Write `None recorded.` when nothing remains.

At the end of Final Results, include available Claude Code and Codex CLI versions from `run_started`
in one compact `Run metadata` bullet. Omit unavailable values. Do not add protocol/schema versions
or a Reproducibility section.

## Final Check

Reread the finished report. Confirm that the five required `##` sections appear once and in order,
the Mermaid block is readable, every material claim is grounded, and Final Results faithfully
reflects `run_closed.judgment`, validation output, risks, and follow-ups.
