# Claude–Codex Orchestrator Plugin

A Claude Code plugin for Codex agent orchestration, live-IDE Codex supervision, durable audit
ledgers, and evidence-recorded consensus; it complements OpenAI's Codex plugin, does not replace it.

The core idea is:

> **Claude orchestrates: it scopes, monitors, reviews, and gates the work. Codex executes scoped implementation work in its native harness and provides independent peer review when a second opinion is useful. Disagreements are worked through with evidence until there is consensus, a recorded Claude decision, or required user action.**

This creates a practical heterogeneous coding-agent ensemble: Claude acts as the long-context
orchestrator and reviewer, while Codex handles scoped implementation, backend work, refactors, test
repair, and second-pass review as reusable monitored agents by default.

---

## What this plugin does

Use this plugin when you want Claude Code to coordinate Codex sessions instead of supervising them
manually.

It helps Claude:

* launch, reuse, or resume scoped Codex workers,
* attach to live Codex IDE sessions from `codex://threads/<thread-uuid>` URLs,
* monitor compact JSONL/rollout streams and classify session status,
* coordinate sequential or parallel Codex work without file or compute conflicts,
* gate shared compute before expensive rollouts,
* record verification evidence and Claude/Codex consensus in a final report.

---

## Requirements

* [Claude Code](https://code.claude.com/docs/en/overview) installed in your IDE or terminal.
* [OpenAI Codex](https://developers.openai.com/codex/cli/reference) installed in your IDE, or available through the Codex CLI.
* Git initialized in the target repository.
* At least one verification path: tests, typecheck, lint, build, benchmark, screenshot, or custom script.

---

## Installation

From inside Claude Code:

```text
/plugin marketplace add alexzh3/codex-orchestrator
/plugin install codex-orchestrator@codex-orchestrator
/reload-plugins
```

---

## Basic usage

Use `orchestrate` for prompt-directed Codex coordination:

```text
/codex-orchestrator:orchestrate

Break this task into scoped Codex agent prompts.

Use this prompt as the scope. Reuse any matching existing Codex agent whose context is relevant. If that session is almost full but still relevant, compact the useful state and continue in the same session. Start a new headless Codex agent with `codex exec --json` only when the task is contextually unrelated, isolation requires it, or I explicitly ask for a fresh session.

Save each Codex prompt under `prompts/` and capture each Codex JSONL stream under `logs/` with the same filename stem. Monitor each JSONL stream with parser state/tail offsets. Do not edit overlapping files while Codex owns them. Review the diffs and record verification after Codex yields or completes.
```

Use `workflow` only when you want the full end-to-end workflow: ledger setup, planning, Codex plan
review when needed, dispatch, monitoring, review, verification, consensus, and final report.

```text
/codex-orchestrator:workflow
```

Start a Codex task in VS Code or Cursor.

Copy the Codex session URL:

```text
codex://threads/<thread-uuid>
```

For IDE sidebar visibility, start the session in VS Code or Cursor first. Headless Codex sessions
started with `codex exec` use source kind `exec`; they are CLI-resumable but do not appear in the
IDE sidebar.

Then ask Claude:

```text
/codex-orchestrator:orchestrate

Monitor this Codex session:
codex://threads/<thread-uuid>

Review what Codex is doing, detect when it finishes or blocks, verify the diff against the repository, and share any suspected mistakes back with Codex before accepting the result.
```

---

## Commands

Available slash commands:

| Command | What it does |
| --- | --- |
| `/codex-orchestrator:orchestrate` | Invoke the orchestration command for prompt-directed Codex coordination, such as scoped dispatch, monitoring, review, handoff, consensus, or compute gating. |
| `/codex-orchestrator:workflow` | Run the full end-to-end workflow: ledger, planning, Codex plan review when needed, dispatch, monitoring, review, verification, consensus, and report. |
| `/codex-orchestrator:report` | Generate or update `report.md` from evidence already recorded in the run ledger. |

The general orchestration playbook lives in [`commands/orchestrate.md`](./commands/orchestrate.md).
Full end-to-end runs and report regeneration are covered by
[`commands/workflow.md`](./commands/workflow.md) and [`commands/report.md`](./commands/report.md).

---

## Workflow Architecture

```text
User goal
   │
   ▼
Claude Code
Planner / Orchestrator / Reviewer
   │
   ├── creates or validates plan
   ├── asks Codex to review new Claude-created plans during full workflow runs
   ├── scopes Codex agent tasks
   ├── reuses, launches, or resumes Codex agents
   ├── monitors Codex JSONL / IDE event streams
   ├── verifies code, tests, diffs, logs, and artifacts
   ├── detects idle / blocked / complete states
   └── records consensus decisions
   │
   ▼
OpenAI Codex
Agent / Implementer / Peer Reviewer
   │
   ├── runs as reusable monitored Codex agents by default
   ├── can also run inside VS Code / Cursor
   ├── edits files in its native harness
   ├── performs scoped implementation work
   ├── can be resumed from the CLI with `codex exec resume`
   ├── can review Claude-created plans
   └── can review uncommitted diffs
   │
   ▼
Repository
Code / tests / manifests / logs / git history
```

---

## Runtime Files And CLI

Most users can use the slash commands and ignore the Python CLI. `orchestrate` and `workflow`
initialize runtime files internally. The CLI exists for manual debugging, scripted runs, and
inspecting the durable files the agent writes.

```bash
python3 scripts/codex_orch.py init --run-id example --repo .
python3 scripts/codex_orch.py status --run-id example
python3 scripts/codex_orch.py add-verification --run-id example --kind test --command "python3 -m unittest discover -s tests -v" --exit-code 0 --result passed --summary "Unit tests passed"
python3 scripts/codex_orch.py report --run-id example
```

Runtime files live under `.codex-orchestrator/runs/<run-id>/` and are ignored by git:
`state.json` is compact mutable state, `ledger.jsonl` is append-only evidence, and `report.md` is
the human-readable handoff. Codex prompts, JSONL streams, and generated artifacts are grouped under
`prompts/`, `logs/`, and `artifacts/` using matching filename stems where possible. Runtime records
are described by `schemas/codex-orchestrator.schema.json`.
---

## Why not just use OpenAI's Codex plugin?

OpenAI's Codex plugin is the right default for standard review, rescue, background execution, and review-gated coding tasks. This plugin is narrower: it is an orchestration manual plus small local scripts for supervising live IDE sessions, coordinating several Codex workers, gating scarce compute, and preserving review/consensus state outside model context.

The tradeoff is that this reads local Codex session state and may need updates when Codex changes its rollout/event format.

---

## Why this approach?

### 1. Heterogeneous LLM ensembles reduce single-model failure modes

This plugin is built around a **heterogeneous ensemble**, not just multiple sessions from the same model. Claude and Codex come from different model families, different training pipelines, different product harnesses, and often different failure modes.

That diversity is useful because a second model only adds value when it can catch errors the first model is likely to miss. Research on LLM ensembles supports this direction: [LLM-Blender](https://arxiv.org/abs/2306.02561) shows that combining outputs from different LLMs can outperform individual models, [Mixture-of-Agents](https://arxiv.org/abs/2406.04692) explores layered collaboration across multiple LLMs, and [FrugalGPT](https://arxiv.org/abs/2305.05176) shows that routing across models can improve the cost/performance trade-off.

For software engineering specifically, [*Wisdom and Delusion of LLM Ensembles for Code Generation and Repair*](https://arxiv.org/abs/2510.21513) evaluates ten LLMs from five model families and finds that cross-model complementarity can expose solutions missed by the best single model. It also warns that blind consensus can become a "popularity trap," where multiple models converge on the same plausible but wrong answer.

That is why this plugin uses **evidence-based consensus** instead of majority vote:

* Claude proposes or validates the plan and remains the final orchestrator and reviewer.
* Codex provides independent peer review where useful, including risky plans and implementation diffs.
* If Claude and Codex disagree, the disagreement is recorded and worked from artifacts until there is
  `consensus`, `claude_decision`, or `user_action_required`.
* Codex executes a scoped implementation.
* Claude verifies the diff, tests, logs, and artifacts.
* When Claude finds a suspected issue, Codex can also review Claude’s objection.
* Disagreements are resolved using evidence, not vibes.
* The final report records each disagreement or mistake, its root cause when known, the agreed resolution, and the verification evidence.

### 2. Claude is a strong default long-context orchestrator compared to GPT

Claude is also a strong fit for long-context coordination. Anthropic's [1M context release](https://claude.com/blog/1m-context-ga) reports strong long-context benchmark results for Claude Opus 4.6, making Claude a sensible default for maintaining broader task state while Codex handles narrower execution loops.

At the same time, this plugin does not rely on long context alone. Reports like [Context Rot](https://www.trychroma.com/research/context-rot) show that model reliability can degrade as context grows. The workflow therefore keeps important operational state external, auditable, and evidence-based: repository diffs, tests, logs, manifests, and explicit consensus records.

### 3. Cost-aware delegation

Codex may be the cheaper or higher-throughput agent for repetitive coding loops, depending on
the user's plan and limits.

This plugin therefore routes repetitive implementation loops to Codex while preserving Claude's budget for the work where it is most valuable: planning, long-context reasoning, review, orchestration, and final judgment.

### 4. Native harnesses matter

Agent quality is not only model quality. It also depends on the harness: IDE context, shell access, file editing, approvals, session history, logs, sandboxing, and model-specific prompting.

This plugin does not try to wrap Codex through a generic interface. It lets Codex run through its own [CLI](https://developers.openai.com/codex/cli/reference), IDE integration, and [approval/sandbox model](https://developers.openai.com/codex/agent-approvals-security), while Claude runs through [Claude Code](https://code.claude.com/docs/en/overview).

---

## Security model

This plugin is designed for **bounded autonomy**, not unrestricted agent execution; the author is not
responsible for any damage caused. Normal Codex agent tasks should run in `workspace-write`, while
Claude gates elevated operations such as network access, out-of-workspace writes, Docker socket
access, deployments, credentials, or GPU-heavy rollouts.

Do not give Codex `danger-full-access` just to avoid approval friction. If broad access is required,
use a trusted, externally hardened container or VM. Keep secrets out of the workspace where possible,
verify all agent claims against artifacts, and record consensus when Claude and Codex disagree about
a bug, fix, or implementation direction.

---

## Privacy

This plugin does not collect, store, sell, or transmit user data on its own. It provides Claude Code with instructions for coordinating local OpenAI Codex sessions.

When you use the plugin, Claude Code and Codex may inspect local repository files, Codex rollout logs, command output, diffs, tests, generated artifacts, and other context you ask them to review. Treat those inputs as data shared with the Claude Code and Codex environments you run.

Do not expose secrets, credentials, private keys, `.env` files, or sensitive production data to Claude Code or Codex unless you have intentionally configured your environment and permissions for that use.
