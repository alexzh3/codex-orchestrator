---
name: codex-orchestrator-report
description: Author the final report from a completed orchestration run after its descriptive close check.
---

# Report

Use this skill only after orchestration work has finished. Do not start agents, continue tasks, or
write an interim report here. Return to `${CLAUDE_PLUGIN_ROOT}/skills/orchestrate/SKILL.md` or
`${CLAUDE_PLUGIN_ROOT}/skills/workflow/SKILL.md` when more work is needed.

## Preconditions

Confirm that:

- descriptive validation ran before closure and its complete result is recorded in
  `run_closed.validation`;
- every execution has a terminal execution result and every task is terminal;
- `run_closed` is the final journal entry and contains `judgment: passed|blocked`;
- no further run work is planned.

If these conditions are not true, stop and return to orchestration. Never edit the journal merely to
make the report look complete.

Read the complete `journal.jsonl`, then ground each claim in its appropriate source:

- actual delivery: final repository state and diff;
- Claude's checks: verification observations and referenced evidence;
- assigned scope: exact prompts;
- agent claims: exact handoffs;
- lifecycle and chronology: journal entries;
- ambiguous process activity: raw events or direct observation;
- decisions and final judgment: decision and `run_closed` entries.

The journal is working memory, not independent evidence. Use raw events only for ambiguity or
debugging. Surface conflicts and missing facts; do not silently repair them.

## Required Report Structure

Create the final `report.md` once, after closure, as a complete Claude-authored report using exactly
these five top-level sections in this order. Only replace an existing final report when explicitly
asked to correct or regenerate it.

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

Describe material delivered changes from the final repository state and diff, then connect them to
their tasks or agents. Cite important repository files and evidence when useful. Distinguish
complete, blocked, failed, and intentionally unchanged work. Do not reproduce the journal line by
line or treat `execution_result.files_changed` as mechanical attribution.

### Orchestration Graph

Create a readable Mermaid `flowchart TD` from journal chronology, grounded in handoffs, verification
evidence, repository changes, and raw events only when needed. Use this top-to-bottom shape:

- `A_CLAUDE{{"Claude Code<br/>planner · orchestrator"}}`;
- separate non-empty Claude-agent and Codex-agent subgraphs;
- material reviews, checks, decisions, and produced deliverables;
- final judgment and state, including meaningful fix/recheck loops.

Use one node per agent or native session, ordered by first execution. Include its task, recorded
model/effort, main result, and terminal status; combine resumed executions in that session's node.
Label edges concisely (`assign`, `review`, `verified`, `tie-break evidence`, `consensus`,
`claude_decision`, `produced`, `fix required`, `recheck`, `accepted`). Show only evidence that affected
a decision or final judgment. Combine routine passing checks and group related decisions, but keep
Claude decisions, user actions, and unresolved outcomes distinct. Mark reconstructed facts as
`inferred`; never infer verification results, decision outcomes, judgments, or terminal status.

### Consensus

Summarize consequential `decision` entries with outcome, basis, resolution, and risk; state when no
decision was required. Keep consensus, Claude decisions, user actions, accepted risks, and unresolved
outcomes distinct. Describe a fresh Codex review as context-independent; use cross-family only for
recorded Claude-Codex participation. Put missing basis or residual-risk treatment under Risks /
Follow-ups.

### Final Results

Use these subsections in this order:

```markdown
### Gate Result

### Risks / Follow-ups
```

Under `Gate Result`, report `run_closed.judgment`, its summary, and the recorded validation issues
and warnings. Validation is an omission check, not evidence of correctness or the source of the
judgment. This is a human-facing heading, not a separate journal entry. Do not recompute or soften
Claude's recorded judgment.

Under `Risks / Follow-ups`, list unresolved checks, blocked or failed work, user actions, accepted
risks, and concrete next steps. Write `None recorded.` when nothing remains.

At the end of Final Results, include available Claude Code and Codex CLI versions from `run_started`
in one compact `Run metadata` bullet. Omit unavailable values. Do not add protocol/schema versions
or a Reproducibility section.

## Final Check

Reread the finished report. Confirm that the five required `##` sections appear once and in order,
the Mermaid block is readable, every material claim is grounded, and Final Results faithfully
reflects `run_closed.judgment`, validation output, risks, and follow-ups.
