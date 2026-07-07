# Claude–Codex Orchestrator Plugin

A Claude Code plugin that lets Claude run OpenAI Codex coding sessions for you. Claude breaks the
work into tasks, starts or resumes Codex agents, watches them in the CLI or IDE, reviews the diffs,
and records why each result was accepted or rejected.

---

## What this plugin does

Use this plugin when you want Claude Code to manage Codex sessions instead of supervising them by
hand.

It helps Claude:

* start new Codex sessions or resume existing ones with the right context,
* attach to live Codex IDE sessions from `codex://threads/<thread-uuid>` using Codex deeplinks,
* monitor compact JSONL/rollout streams and classify session status,
* coordinate sequential or parallel Codex work without file or compute conflicts,
* check shared compute before expensive local runs, such as GPU-heavy tests or research rollouts,
* record verification evidence and Claude/Codex consensus in a final report.

Basically, Claude acts as the long-context orchestrator and reviewer, while Codex handles scoped implementation,
backend work, refactors, test repair, and second-pass review as reusable monitored agents by default.

---

## Requirements

* [Claude Code](https://code.claude.com/docs/en/overview) installed in your IDE or terminal.
* [OpenAI Codex](https://developers.openai.com/codex/cli/reference) installed in your IDE, or available through the Codex CLI.
* Git initialized in the target repository when using worktree isolation or branch-based review.
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

## Skills and slash commands

Available slash commands:

| Command | What it does |
| --- | --- |
| `/codex-orchestrator:orchestrate` | Invoke the orchestration command for prompt-directed Codex coordination, such as scoped dispatch, monitoring, review, handoff, consensus, or compute gating. |
| `/codex-orchestrator:workflow` | Run the full end-to-end workflow: ledger, planning, Codex plan review when needed, dispatch, monitoring, review, verification, consensus, and report. |
| `/codex-orchestrator:report` | Generate or update `report.md` from evidence already recorded in the run ledger. |

The orchestration playbooks live in the skills:
[`skills/orchestrate/SKILL.md`](./skills/orchestrate/SKILL.md),
[`skills/workflow/SKILL.md`](./skills/workflow/SKILL.md), and
[`skills/report/SKILL.md`](./skills/report/SKILL.md). The `commands/*.md` files are thin slash-command
triggers that load those skills.

---

## Evidence-based consensus

The plugin does not accept `"Codex says tests pass"` as evidence. Test output is evidence. Diffs are evidence. Logs are evidence. Artifacts are evidence. A model's narration is only a claim until checked.

Example lifecycle:

1. Claude records a failed verification:

   ```json
   {
     "type": "verification",
     "id": "V1",
     "kind": "test",
     "result": "failed",
     "command": "python3 -m unittest discover -s tests -v",
     "task_id": "T001",
     "acceptance_test": true,
     "artifacts": ["logs/unit-tests-before.txt"]
   }
   ```

2. Codex patches the code.

3. Claude reruns the same command and records a passing verification:

   ```json
   {
     "type": "verification",
     "id": "V2",
     "kind": "test",
     "result": "passed",
     "command": "python3 -m unittest discover -s tests -v",
     "task_id": "T001",
     "acceptance_test": true,
     "artifacts": ["logs/unit-tests-after.txt"]
   }
   ```

4. Claude records a consensus / resolution record:

   ```json
   {
     "type": "consensus",
     "outcome": "consensus",
     "finding": "Unit tests failed before the fix.",
     "resolution": "The same command passed after the patch.",
     "resolution_basis": "rerun_passed",
     "clears": ["verification:V1"],
     "evidence_refs": ["verification:V2"]
   }
   ```

5. `gate` reads the ledger and allows the run only if no unresolved blockers remain.

A failed runnable check clears only by a matching passing rerun or an explicit allowed override. Acceptance tests are stricter: a failed executable acceptance test clears only by a real passing rerun. Human-readable discussion is not enough.

See `docs/consensus-and-reviews.md` for the full details.

---

## Orchestration graph

Generated reports include a session-centric orchestration graph that traces tasks, Codex sessions,
verification evidence, reviews, consensus, and the final gate. Session nodes show the model/effort
when recorded plus the harness mode and status, and a fresh restart of an agent becomes a new node.
Evidence that affects acceptance is a node because it may need to be inspected, cited, cleared, or
replayed; consensus is shown as a resolution gate, not an agent. See
[`docs/orchestration-graph.md`](./docs/orchestration-graph.md) for the grammar and a worked example.

---

## Workflow Architecture

When using the `workflow` command, it will follow this architecture:

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

## Runtime Files

Runtime files live under `.codex-orchestrator/runs/<run-id>/` and are ignored by git:
`state.json` is compact mutable state, `ledger.jsonl` is append-only evidence, and `report.md` is
the human-readable handoff. Codex prompts, JSONL streams, and generated artifacts are grouped under
`prompts/`, `logs/`, and `artifacts/` using matching filename stems where possible. Runtime records
are described by `schemas/codex-orchestrator.schema.json`.

---

## Benchmarks

The current public benchmark is an OpenThoughts-TBLite / Terminal-Bench-style comparison on the 10 hardest tasks by published success rate. Each cell is one run per task/configuration, so the result is directional rather than statistical.

Summary (figures for `codex-orchestrator` v0.4.1):

| Regime               | Solo Claude (Opus 4.8, max reasoning) | Solo Codex (gpt-5.5, xhigh) | `codex-orchestrator` |
| -------------------- | ------------------------------------: | --------------------------: | -------------------: |
| Timed harness        |                                  8/10 |                        8/10 |                 6/10 |
| Timeout lifted       |                                  8/10 |                        8/10 |                 9/10 |
| Total tokens (as-run)|                                14.49M |                       5.44M |               31.77M |

The orchestrator is Claude Opus 4.8 at max reasoning effort; the implementer is Codex gpt-5.5 at
reasoning effort xhigh. See `docs/benchmarks.md` for the curated result, per-task breakdowns, and the Claude/Codex token split.

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
* When Claude finds a suspected issue, Codex can also review Claude's objection.
* Disagreements are resolved using evidence, not vibes.
* Consensus records can include a machine-checkable resolution basis (`rerun_passed`,
  `accepted_risk`, `user_override`, etc.) so failed executable checks require real rerun evidence or
  an explicit override; see [`docs/consensus-and-reviews.md`](docs/consensus-and-reviews.md).
* The final report records each disagreement or mistake, its root cause when known, the agreed resolution, and the verification evidence.

### 2. Claude is a strong default long-context orchestrator compared to GPT

Claude is also a strong fit for long-context coordination. Anthropic's [1M context release](https://claude.com/blog/1m-context-ga) reports strong long-context benchmark results for Claude Opus 4.6, making Claude a sensible default for maintaining broader task state while Codex handles narrower execution loops.

At the same time, this plugin does not rely on long context alone. Reports like [Context Rot](https://www.trychroma.com/research/context-rot) show that model reliability can degrade as context grows. The workflow therefore keeps important operational state external, auditable, and evidence-based: repository diffs, tests, logs, manifests, and explicit consensus records.

### 3. Native harnesses matter

Agent quality is not only model quality. It also depends on the harness: IDE context, shell access, file editing, approvals, session history, logs, sandboxing, and model-specific prompting.

This shows up empirically. On the [Terminal-Bench 2.1 leaderboard](https://www.tbench.ai/leaderboard/terminal-bench/2.1) the same model scores differently depending on the harness driving it, and the **Codex CLI harness (with gpt-5.5) is the top-scoring agent harness** — narrowly ahead of Claude Code with Fable 5. As a solo terminal executor, Codex CLI is currently the strongest harness, which is a direct reason to route scoped implementation to Codex in its own harness.

---

## Limitations

- **Most review loops are sequential.** The workflow is built on recorded evidence
  and consensus — Claude scopes and reviews, Codex implements, and each step depends on the other's
  output — so the two models cannot work the same task at the same time. You wait for one to finish
  before the other continues, which makes the **total wall-clock time to complete a task longer** than
  a single solo agent, especially with Claude set to maximum reasoning effort. The
  [benchmarks](#benchmarks) reflect this: the orchestrated runs are slower than the solo baselines.
- **The trade-off is oversight and token efficiency.** Keeping state in the ledger, reports, and
  artifacts — instead of manually re-feeding context back and forth between two models — means the
  orchestrated approach uses **fewer tokens on average than driving the two models by hand**. You
  spend some extra wall-clock time to get supervised, auditable work at a lower token cost.

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
