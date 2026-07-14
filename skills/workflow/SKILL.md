---
name: codex-orchestrator-workflow
description: Run the full Codex orchestration workflow end to end.
---

# Workflow

Use this skill for one complete run. This skill owns the lifecycle from planning through the final
report. Use `${CLAUDE_PLUGIN_ROOT}/skills/orchestrate/SKILL.md` for each focused Codex-agent
execution, review, or verification cycle.

## Optional Role Policy

`.codex-orchestrator/config.ini` is an opt-in, repository-local performance policy. Never create it
as a side effect of starting a run. If the user explicitly requests role configuration, initialize
it once without overwriting an existing file:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/codex_orch_tools.py" config init --repo <repo>
```

When the file exists, validate it before planning or launching an agent and inspect the resolved
role policy as needed:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/codex_orch_tools.py" config check --repo <repo>
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/codex_orch_tools.py" config show \
  --repo <repo> --role implementation --json
```

An invalid existing policy stops the workflow until corrected. If the file is absent, do not
create one, do not choose or pass a plugin reasoning effort, and let the Codex child command use
its native `config.toml` and built-in defaults unchanged.

With an active policy, Claude selects the lowest allowed effort adequate for each execution:

- If a manually edited policy exposes `low`, `medium`, or `high`, reserve them respectively for
  trivial mechanical work, small well-bounded work, or moderate contained reasoning.
- For `implementation`, use `xhigh` for bounded work with clear requirements and limited context;
  use `max` for difficult, ambiguous, cross-cutting, or high-risk work; use `ultra` for very broad,
  context-heavy, or meaningfully decomposable work.
- For `review`, `planning`, and `planning_review`, use `max` for one focused, coherent target and
  `ultra` for broad, multi-domain, context-heavy, or parallelizable analysis.

Nested subagents created during an Ultra execution inherit the parent execution's sandbox and
ownership boundaries and remain part of that named execution; do not assign them separate journal
identities. Existing overlap, worktree, and compute rules still apply.

Select again for every resumed execution rather than inheriting the prior effort automatically.
The configured model, effort, and Fast service tier are execution inputs, not evidence of quality;
Claude still verifies the result.

## Run Initialization

From the target Git worktree, exclude run data locally before creating it:

```bash
REPO="$(git rev-parse --show-toplevel)"
cd "$REPO"
EXCLUDE_FILE="$(git rev-parse --git-path info/exclude)"
grep -qxF '/.codex-orchestrator/' "$EXCLUDE_FILE" ||
  printf '\n/.codex-orchestrator/\n' >> "$EXCLUDE_FILE"
grep -qxF '/.codex-orchestrator/' "$EXCLUDE_FILE"
git check-ignore -q .codex-orchestrator/.ignore-check
git rev-parse HEAD
git branch --show-current
git status --short --untracked-files=all
```

Use only this local exclude; do not edit the tracked `.gitignore`. Record the concise original goal,
`REPO`, full starting HEAD, attached branch when the branch output is nonempty, and exact status
lines as `goal`, `repo`, `repo_head`, optional `repo_branch`, and `repo_status` in `run_started`.
Do not create the run unless both exclude checks succeed. Initially dirty paths are pre-existing
user work; if planned work overlaps them, use an isolated clean worktree or get user direction
rather than claiming those changes.

## Full Workflow

1. Inspect the repository and user context to understand the goal and relevant constraints.
2. Perform Run Initialization, create `.codex-orchestrator/runs/<run-id>/journal.jsonl`, and append
   `run_started` with the concise original goal, absolute repository path, captured Git baseline,
   plugin ref, and available Claude and Codex versions.
3. Claude turns the goal into a concrete plan draft with expected deliverables, acceptance
   criteria, risks, and verification paths.
4. For a consequential or hard-to-reverse design choice, optionally start a fresh, read-only
   `planning` agent (`codex-plan-NN`) to propose an independent approach from only the goal,
   constraints, and acceptance criteria, recording it as its own task and focused agent cycle. Ask
   a separate fresh, read-only `planning_review` agent (`codex-plan-review-NN`) to critique
   Claude's draft plan when a second opinion materially reduces risk; record that
   review as a task and focused agent cycle. Claude compares the results using evidence rather than
   agent count and finalizes the plan. Follow
   `${CLAUDE_PLUGIN_ROOT}/skills/orchestrate/references/planning.md` for both roles.
5. Split the finalized plan into active `task` entries with goals, acceptance criteria, and
   allowed/owned `files`. Serialize overlapping work or use isolated worktrees.
6. For each task, use the orchestrate skill to assign or resume a Codex agent, capture its prompt,
   events, and handoff, and independently verify the result. Repeat focused fix or review cycles as
   needed.
7. Record only consequential resolutions or user dependencies as `decision`. Append a terminal
   `task` entry only after its acceptance criteria have been evaluated.
8. When every task is terminal, re-read the complete journal and inspect the final repository state
   and diff.
9. Run the descriptive close check:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/codex_orch_tools.py" validate \
  .codex-orchestrator/runs/<run-id>
```

10. Resolve omissions that can be corrected by appending, and inspect every non-passing
    verification. Never rewrite journal history. If a duplicate identity or another structural
    conflict cannot be corrected by appending, retain the run and start a successor as defined by
    the orchestration contract. Otherwise append one final `run_closed` entry with
    `judgment: passed|blocked`, the exact validation result, unresolved risks, and follow-ups.
    Validation detects omissions; Claude decides acceptance.
11. After `run_closed`, invoke `${CLAUDE_PLUGIN_ROOT}/skills/report/SKILL.md` to create `report.md`
    once.

The canonical close sequence is `validate → run_closed → report.md`. Validation never decides
acceptance, and the final report never repairs or rewrites journal history.
