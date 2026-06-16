# Claude–Codex Orchestrator Skill

A Claude Code skill for coordinating **OpenAI Codex** sessions from **Claude Code**, especially when both are used inside IDEs like **Cursor** or **VS Code**.

The core workflow is:

> **Claude plans, monitors, reviews, and gates. Codex executes scoped implementation work in its own native harness. Both agents must converge before changes are accepted.**

This creates a practical heterogeneous coding-agent ensemble: Claude acts as the long-context orchestrator and reviewer, while Codex handles scoped implementation, backend work, refactors, test repair, and second-pass review.

The actual operational playbook lives in [`skills/codex-orchestrator/SKILL.md`](./skills/codex-orchestrator/SKILL.md). This README only explains the motivation, setup, and intended workflow.

---

## What this skill does

Use this skill when you want Claude Code to coordinate one or more Codex sessions.

It can:

* locate a live Codex IDE session from a `codex://threads/<thread-uuid>` URL,
* read Codex rollout logs without loading huge files into context,
* detect whether Codex is active, complete, idle, or blocked on approval,
* resume or drive Codex through [`codex exec`](https://developers.openai.com/codex/cli/reference),
* run Codex as a headless executor,
* ask Codex to review uncommitted changes,
* coordinate multiple Codex sessions sequentially or in parallel,
* gate shared compute before expensive rollouts,
* and produce a final evidence-based report.

---

## Why this approach?

### 1. Heterogeneous LLM ensembles reduce single-model failure modes

This skill is built around a **heterogeneous ensemble**, not just multiple sessions from the same model. Claude and Codex come from different model families, different training pipelines, different product harnesses, and often different failure modes.

That diversity is useful because a second model only adds value when it can catch errors the first model is likely to miss. Research on LLM ensembles supports this direction: [LLM-Blender](https://arxiv.org/abs/2306.02561) shows that combining outputs from different LLMs can outperform individual models, [Mixture-of-Agents](https://arxiv.org/abs/2406.04692) explores layered collaboration across multiple LLMs, and [FrugalGPT](https://arxiv.org/abs/2305.05176) shows that routing across models can improve the cost/performance trade-off.

For software engineering specifically, [*Wisdom and Delusion of LLM Ensembles for Code Generation and Repair*](https://arxiv.org/abs/2510.21513) evaluates ten LLMs from five model families and finds that cross-model complementarity can expose solutions missed by the best single model. It also warns that blind consensus can become a “popularity trap,” where multiple models converge on the same plausible but wrong answer.

That is why this skill uses **evidence-based consensus** instead of majority vote:

* Claude proposes or validates the plan.
* Codex executes a scoped implementation.
* Claude verifies the diff, tests, logs, and artifacts.
* Codex reviews Claude’s objections or its own uncommitted diff.
* Disagreements are resolved using evidence, not vibes.
* The final report records the issue, root cause, fix, and verification result.

### 2. Claude is a strong default long-context orchestrator compared to GPT
Claude is also a strong fit for long-context coordination. Anthropic’s [1M context release](https://claude.com/blog/1m-context-ga) reports strong long-context benchmark results for Claude Opus 4.6, making Claude a sensible default for maintaining broader task state while Codex handles narrower execution loops.

At the same time, this skill does not rely on long context alone. Reports like [Context Rot](https://www.trychroma.com/research/context-rot) show that model reliability can degrade as context grows. The workflow therefore keeps important operational state external, auditable, and evidence-based: repository diffs, tests, logs, manifests, and explicit consensus records.

### 3. Cost-aware delegation

Codex currently offers a substantially higher effective usage allowance for many coding workflows, especially on higher ChatGPT plans, whereas Claude is way more restrictive with their usage limits.

This skill therefore routes repetitive implementation loops to Codex while preserving Claude’s budget for the work where it is most valuable: planning, long-context reasoning, review, orchestration, and final judgment.

The point is not that Codex is always cheaper or always better. The point is that, under current plan structures, Codex is often the more practical execution budget, while Claude is often the more valuable orchestration budget.

### 4. Native harnesses matter

Agent quality is not only model quality. It also depends on the harness: IDE context, shell access, file editing, approvals, session history, logs, sandboxing, and model-specific prompting.

This skill does not try to wrap Codex through a generic interface. It lets Codex run through its own [CLI](https://developers.openai.com/codex/cli/reference), IDE integration, and [approval/sandbox model](https://developers.openai.com/codex/agent-approvals-security), while Claude runs through [Claude Code](https://code.claude.com/docs/en/overview).

---

## Installation

From inside Claude Code:

```text
/plugin marketplace add alexzh3/codex-orchestrator
/plugin install codex-orchestrator@codex-orchestrator
/reload-plugins
```

Then invoke:

```text
/codex-orchestrator:codex-orchestrator
```

## Requirements

* [Claude Code](https://code.claude.com/docs/en/overview) installed in your IDE or terminal.
* [OpenAI Codex](https://developers.openai.com/codex/cli/reference) installed in your IDE, or available through the Codex CLI.
* Git initialized in the target repository.
* At least one verification path: tests, typecheck, lint, build, benchmark, screenshot, or custom script.

---

## Basic usage

Start a Codex task in VS Code or Cursor.

Copy the Codex session URL:

```text
codex://threads/<thread-uuid>
```

Then ask Claude:

```text
/codex-orchestrator:codex-orchestrator

Monitor this Codex session:
codex://threads/<thread-uuid>

Review what Codex is doing, detect when it finishes or blocks, verify the diff against the repository, and do not accept the result until Claude and Codex agree on the final fix.
```

For a headless handoff:

```text
/codex-orchestrator:codex-orchestrator

Ask Codex to implement the next scoped task using codex exec.
Run Codex in workspace-write mode with approval_policy=never.
After Codex finishes, review the diff, run verification, and ask Codex to review any suspicious changes before accepting.
```

---

## Hypothetical Architecture

```text
User goal
   │
   ▼
Claude Code
Planner / Orchestrator / Reviewer
   │
   ├── creates or validates plan
   ├── scopes Codex tasks
   ├── monitors Codex progress
   ├── verifies code, tests, diffs, logs, and artifacts
   ├── detects idle / blocked / complete states
   └── records consensus decisions
   │
   ▼
OpenAI Codex
Executor / Implementer / Peer Reviewer
   │
   ├── runs inside VS Code / Cursor / CLI
   ├── edits files in its native harness
   ├── performs scoped implementation work
   ├── can be resumed via codex exec
   └── can review uncommitted diffs
   │
   ▼
Repository
Code / tests / manifests / logs / git history
```

---

## Security model

This skill is designed for **bounded autonomy**, not unrestricted agent execution; the author is not responsible for any damage caused.

Default assumptions:

* Codex runs in `workspace-write` for normal executor tasks.
* Claude gates dangerous or expensive actions before they run.
* Network access, out-of-workspace writes, Docker socket access, deployments, credentials, and GPU-heavy rollouts are treated as elevated operations that require explicit user authorization or a deliberately configured permission profile.
* Codex should not receive `danger-full-access` just to avoid approval friction.
* If broad access is required, run Codex only inside a trusted, externally hardened environment such as a dedicated container or VM.
* Secrets should not be assumed safe just because Codex is sandboxed. Keep secrets out of the workspace where possible, deny `.env` files in custom permission profiles, and avoid exposing unnecessary credentials to agent-run commands.
* All agent claims must be verified against artifacts: diffs, tests, logs, manifests, build output, or benchmark results.
* Consensus decisions should be recorded when Claude and Codex disagree about a bug, fix, or implementation direction.
