# Claude–Codex Orchestrator Skill

A Claude Code skill for live-IDE Codex supervision, multi-session coordination, durable audit ledgers, and evidence-recorded consensus; it complements OpenAI's Codex plugin, does not replace it.

The core workflow is:

> **Claude plans, monitors, reviews, and gates. Codex executes scoped implementation work in its own native harness. When Claude finds a suspected issue, Claude shares it back with Codex and records the evidence-based resolution before accepting the work.**

This creates a practical heterogeneous coding-agent ensemble: Claude acts as the long-context orchestrator and reviewer, while Codex handles scoped implementation, backend work, refactors, test repair, and second-pass review.

The actual operational playbook starts in [`skills/codex-orchestrator/SKILL.md`](./skills/codex-orchestrator/SKILL.md). That file is intentionally compact for token usage; detailed procedures live in [`skills/codex-orchestrator/references/`](./skills/codex-orchestrator/references/) and are opened only for the relevant command or step. This README only explains the motivation, setup, and intended workflow.

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
* and record evidence, verification results, and any Claude/Codex disagreement resolutions in the final report.

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
## Installation

From inside Claude Code:

```text
/plugin marketplace add alexzh3/codex-orchestrator
/plugin install codex-orchestrator@codex-orchestrator
/reload-plugins
```

For the full orchestration workflow, invoke:

```text
/codex-orchestrator:workflow
```

## Slash commands

Use the workflow command when you want Claude to run the whole orchestration workflow end to end:

```text
/codex-orchestrator:workflow
```

Use `start-run` only when you want to open a tracked run ledger:

```text
/codex-orchestrator:start-run
```

That command only creates:

```text
.codex-orchestrator/runs/<run-id>/
  state.json
  ledger.jsonl
  report.md
```

It does not run tests, review diffs, resolve consensus, or generate the final report.

Available commands:

```text
/codex-orchestrator:workflow       # run setup, monitoring, review, verification, consensus, and report
/codex-orchestrator:start-run      # open state.json, ledger.jsonl, and report.md only
/codex-orchestrator:monitor        # inspect Codex IDE or exec status without loading full logs
/codex-orchestrator:review         # review Codex output and record verification evidence
/codex-orchestrator:consensus      # resolve a suspected bug or disagreement with evidence
/codex-orchestrator:report         # generate or update report.md after evidence is recorded
/codex-orchestrator:handoff        # prepare a scoped Codex handoff, using worktrees when needed
/codex-orchestrator:gate-compute   # check shared GPU/Docker/Isaac resources before expensive work
```

Typical manual sequence:

```text
/codex-orchestrator:start-run
/codex-orchestrator:monitor        # when supervising an active Codex session
/codex-orchestrator:review
/codex-orchestrator:consensus      # only for a suspected bug or disagreement
/codex-orchestrator:report
```

Use `workflow` for the full flow in one command, or chain the step commands when you want manual
control.

## Requirements

* [Claude Code](https://code.claude.com/docs/en/overview) installed in your IDE or terminal.
* [OpenAI Codex](https://developers.openai.com/codex/cli/reference) installed in your IDE, or available through the Codex CLI.
* Git initialized in the target repository.
* At least one verification path: tests, typecheck, lint, build, benchmark, screenshot, or custom script.

---

## Durable ledger CLI

Create a run ledger before supervising or dispatching Codex:

```bash
python3 scripts/codex_orch.py init --run-id example --repo .
```

After later review work, inspect compact state, record verification evidence, and generate the
handoff report:

```bash
python3 scripts/codex_orch.py status --run-id example
python3 scripts/codex_orch.py add-verification --run-id example --kind test --command "python3 -m unittest discover -s tests -v" --exit-code 0 --result passed --summary "Unit tests passed"
python3 scripts/codex_orch.py report --run-id example
```

Runtime ledgers live under `.codex-orchestrator/runs/<run-id>/` and are ignored by git. Each run uses
`state.json` for compact mutable state, `ledger.jsonl` for append-only events and evidence, and
`report.md` for human-readable review, consensus, and final report sections.

---

## Basic usage

Start a Codex task in VS Code or Cursor.

Copy the Codex session URL:

```text
codex://threads/<thread-uuid>
```

For IDE sidebar visibility, start the session in VS Code or Cursor first. Headless `codex exec`
sessions use source kind `exec`; if you explicitly ask the skill for IDE visibility, it will use a
local metadata workaround which might have future compatibility implications.

Then ask Claude:

```text
/codex-orchestrator:workflow

Monitor this Codex session:
codex://threads/<thread-uuid>

Review what Codex is doing, detect when it finishes or blocks, verify the diff against the repository, and share any suspected mistakes back with Codex before accepting the result.
```

For a headless handoff:

```text
/codex-orchestrator:workflow

Ask Codex to implement the next scoped task using codex exec.
Run Codex in workspace-write mode with approval_policy=never.
After Codex finishes, review the diff, run verification, and ask Codex to review any suspicious changes before accepting.
```

---

## When to use this instead of /codex:rescue

Use this skill when:

* an existing Codex IDE session needs supervision without discarding its live context,
* multiple sessions may race on files, branches, artifacts, or shared GPU/compute,
* a durable audit trail is needed for thesis, research, or handoff review,
* artifacts, manifests, logs, and generated outputs must be verified before acceptance,
* disagreements need to be resolved with recorded evidence rather than a one-shot rescue.

## Why not just use OpenAI's Codex plugin?

OpenAI's Codex plugin is the right default for standard review, rescue, background execution, and review-gated coding tasks. This skill is narrower: it is an orchestration manual plus small local scripts for supervising live IDE sessions, coordinating several Codex workers, gating scarce compute, and preserving review/consensus state outside model context.

The tradeoff is that this reads local Codex session state and may need updates when Codex changes its rollout/event format.

---

## Why this approach?

### 1. Heterogeneous LLM ensembles reduce single-model failure modes

This skill is built around a **heterogeneous ensemble**, not just multiple sessions from the same model. Claude and Codex come from different model families, different training pipelines, different product harnesses, and often different failure modes.

That diversity is useful because a second model only adds value when it can catch errors the first model is likely to miss. Research on LLM ensembles supports this direction: [LLM-Blender](https://arxiv.org/abs/2306.02561) shows that combining outputs from different LLMs can outperform individual models, [Mixture-of-Agents](https://arxiv.org/abs/2406.04692) explores layered collaboration across multiple LLMs, and [FrugalGPT](https://arxiv.org/abs/2305.05176) shows that routing across models can improve the cost/performance trade-off.

For software engineering specifically, [*Wisdom and Delusion of LLM Ensembles for Code Generation and Repair*](https://arxiv.org/abs/2510.21513) evaluates ten LLMs from five model families and finds that cross-model complementarity can expose solutions missed by the best single model. It also warns that blind consensus can become a "popularity trap," where multiple models converge on the same plausible but wrong answer.

That is why this skill uses **evidence-based consensus** instead of majority vote:

* Claude proposes or validates the plan.
* Codex executes a scoped implementation.
* Claude verifies the diff, tests, logs, and artifacts.
* When Claude finds a suspected issue, Codex reviews Claude’s objection or the uncommitted diff.
* Disagreements are resolved using evidence, not vibes.
* The final report records each disagreement or mistake, its root cause when known, the agreed resolution, and the verification evidence.

### 2. Claude is a strong default long-context orchestrator compared to GPT

Claude is also a strong fit for long-context coordination. Anthropic's [1M context release](https://claude.com/blog/1m-context-ga) reports strong long-context benchmark results for Claude Opus 4.6, making Claude a sensible default for maintaining broader task state while Codex handles narrower execution loops.

At the same time, this skill does not rely on long context alone. Reports like [Context Rot](https://www.trychroma.com/research/context-rot) show that model reliability can degrade as context grows. The workflow therefore keeps important operational state external, auditable, and evidence-based: repository diffs, tests, logs, manifests, and explicit consensus records.

### 3. Cost-aware delegation

Codex currently offers a substantially higher effective usage allowance for many coding workflows, especially on higher ChatGPT plans, whereas Claude is way more restrictive with their usage limits.

This skill therefore routes repetitive implementation loops to Codex while preserving Claude's budget for the work where it is most valuable: planning, long-context reasoning, review, orchestration, and final judgment.


### 4. Native harnesses matter

Agent quality is not only model quality. It also depends on the harness: IDE context, shell access, file editing, approvals, session history, logs, sandboxing, and model-specific prompting.

This skill does not try to wrap Codex through a generic interface. It lets Codex run through its own [CLI](https://developers.openai.com/codex/cli/reference), IDE integration, and [approval/sandbox model](https://developers.openai.com/codex/agent-approvals-security), while Claude runs through [Claude Code](https://code.claude.com/docs/en/overview).

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

---

## Privacy

This plugin does not collect, store, sell, or transmit user data on its own. It provides Claude Code with instructions for coordinating local OpenAI Codex sessions.

When you use the plugin, Claude Code and Codex may inspect local repository files, Codex rollout logs, command output, diffs, tests, generated artifacts, and other context you ask them to review. Treat those inputs as data shared with the Claude Code and Codex environments you run.

Do not expose secrets, credentials, private keys, `.env` files, or sensitive production data to Claude Code or Codex unless you have intentionally configured your environment and permissions for that use.
