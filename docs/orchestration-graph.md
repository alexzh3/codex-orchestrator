# Orchestration Graph

The generated `## Orchestration Graph` in `report.md` is an agentic trace graph of the run ledger.

> Edges are actions only when the action is transient. Nodes are artifacts when the result must be
> inspected, cited, cleared, or replayed. Agent nodes are active reasoning entities; consensus is a
> resolution gate, not an agent (a consensus record can mean agreement, a Claude decision, or user
> action required).

## Shape Grammar

| Shape | Generated node | Meaning |
| --- | --- | --- |
| Hexagon | `A_CLAUDE{{"Claude Code<br/>planner · orchestrator"}}` | Claude control plane. |
| Subroutine | `A_<SLUG>[["agent · role<br/>session n · model · effort<br/>mode · status"]]` | One non-hub Codex session. Later fresh restarts get `_S<n>` node ids and a `session n (fresh restart)` label. |
| Rectangle | `T_<slug>["task_id: compact title (status)"]` | Task artifact from task ledger records. Titles are compacted; ids and status stay visible. |
| Parallelogram | `V<n>[/"Vn · kind: result"/]`, `R<n>[/"Rn · kind review: result"/]` | Evidence that can be inspected, cited, cleared, or replayed. Run-wide review labels append ` · run-wide`. |
| Diamond | `C<n>{"consensus: outcome"}`, `G{"gate: ok"}` | Consensus and gate decisions. |
| Triple circle | `DONE((("run accepted")))` | Accepted terminal state when the latest gate passes. |

## Edge Grammar

| Edge | Ledger event label | Meaning |
| --- | --- | --- |
| `-->` | `task_created`, `dispatch ×N`, `produced`, positional task-to-evidence links, `consensus`, gate transitions | Transient orchestration action or structural trace link. `task_created` appears only for tasks with no session delivery edge. |
| `==>` | Session-to-task delivery status such as `complete`, `blocked`, or `failed` | State-changing work delivered by a Codex session. |
| `-.->` | `clears` | Read-only citation from rendered evidence to a consensus record. |

Dispatch edges are collapsed to one edge per session, for example `dispatch ×2`; a single-dispatch
session includes the task id in the edge label. Evidence is placed between its subject task and the
gate: `T_x --> Vn --> G` or `T_x --> Rn --> G`. Run-wide evidence has no task parent and goes
directly to `G`. Reviews produced by a non-hub peer reviewer have a `produced` edge from the
reviewer session to the review node. Failed reviews loop back to the session that delivered the
reviewed task.

The generated graph does not emit producer edges from Claude such as `review` or `add_verification`,
and it does not emit labeled evidence subject edges such as `reviews` or `covers`; pipeline position
shows the subject.

## Node IDs

| Prefix | Source |
| --- | --- |
| `A_CLAUDE` | Claude control-plane hub; `claude` and `claude-code` reviewer names collapse here. |
| `A_<SLUG>` | First session for a non-hub agent name, uppercased with non-alphanumeric characters changed to `_`; collisions get `_2`, `_3`. |
| `A_<SLUG>_S<n>` | Later fresh session restart for that agent, with the same collision rules. |
| `T...` | Task IDs, slugged from `task_created` / task protocol records. |
| `V<n>` | Non-review verification records in ledger order. |
| `R<n>` | Review-kind verifications and typed `review` records in ledger order. |
| `C<n>` | Consensus records in ledger order. |
| `G`, `DONE` | Latest gate result and accepted terminal state. |

## Evidence Cross-References

`V<n>` and `R<n>` are stable within a rendered report and are assigned in ledger order. The same
ids appear in the graph and in the `## Consensus` detail headings, for example
`- **V1 — Test** (passed)` and `- **R1 — Diff Review** (passed)`. Graph labels stay compact and
carry only the id, kind, result, and optional run-wide suffix; the full summary, command,
artifacts, findings, and notes live in the Consensus details.

## Status Colors

The graph uses three optional classes:

| Class | Meaning |
| --- | --- |
| `ok` | Passed/completed/accepted outcomes. |
| `attention` | Skipped, inconclusive, needs-human-review, user-action-required, unresolved, or other non-final outcomes. |
| `bad` | Failed, blocked, or rejected outcomes. |

Session nodes and `A_CLAUDE` are neutral and never colored because they are entities, not outcomes.
Color encodes outcome only, shape encodes type, and labels always carry the state word so color
never needs to carry meaning by itself.

## Static Architecture

```mermaid
flowchart TD
    U([User goal / GitHub issue / benchmark task])
    subgraph CONTROL["Claude control plane"]
        Claude{{"Claude Code<br/>planner · monitor · reviewer<br/>consensus broker · compute gate"}}
    end
    subgraph CODEX["Codex agent sessions"]
        CodexImpl[["Codex implementation session<br/>Goal: implement scoped task"]]
        CodexReview[["Codex peer-review session<br/>Goal: independently review plan/diff"]]
    end
    subgraph STATE["Durable state and evidence"]
        Ledger[("Run ledger<br/>state.json + ledger.jsonl")]
        Prompts[/"prompts/*.md"/]
        Logs[/"logs/*.jsonl"/]
        Repo[("Repository / branch / worktree")]
        Evidence[/"Diffs, test output, build logs, artifacts"/]
        Report[/"report.md"/]
    end
    subgraph GATES["Review, consensus, and acceptance gates"]
        FileGate{"File claims conflict?"}
        ReviewGate{"Blocking finding?"}
        ConsensusGate{"Valid resolution basis?"}
        Gate{"gate ok?"}
        Doctor{"doctor clean?"}
    end
    Done((("Accepted handoff")))
    U -->|"start workflow"| Claude
    Claude -->|"ensure-run / run_meta"| Ledger
    Claude -->|"task_created: goal, context, constraints"| Ledger
    Claude -->|"claim-files / check-conflicts"| FileGate
    FileGate -->|"conflict: serialize or isolate"| Claude
    FileGate -->|"no conflict: render-prompt"| Prompts
    Claude -->|"optional: request plan review"| CodexReview
    Prompts -.->|"prompt_path"| CodexReview
    CodexReview -->|"review: plan verdict"| Ledger
    Claude -->|"dispatch_started: scoped implementation"| CodexImpl
    Prompts -.->|"prompt_path"| CodexImpl
    CodexImpl ==>|"edit files / run scoped work"| Repo
    CodexImpl -->|"JSONL rollout stream"| Logs
    Claude -.->|"monitor active / idle / blocked / complete"| Logs
    CodexImpl -->|"dispatch_completed + task_checkpoint"| Ledger
    Repo -->|"git diff"| Evidence
    Logs -->|"test/build/lint output"| Evidence
    Claude -->|"request diff review"| CodexReview
    Evidence -.->|"inspect artifacts"| CodexReview
    Repo -.->|"read code context"| CodexReview
    CodexReview -->|"review: findings / pass / fail"| Ledger
    Claude ==>|"add-verification: command + result + artifacts"| Ledger
    Ledger -->|"evaluate review + verification records"| ReviewGate
    ReviewGate -->|"blocked: fix required"| CodexImpl
    ReviewGate -->|"no unresolved blocker"| ConsensusGate
    Claude -->|"record consensus / decision / user action required"| ConsensusGate
    Evidence -.->|"evidence_refs"| ConsensusGate
    ConsensusGate -->|"invalid basis or user action required"| Claude
    ConsensusGate -->|"clears verification/finding refs"| Gate
    Ledger -->|"gate reads source of truth"| Gate
    Gate -->|"blocked"| Claude
    Gate -->|"ok: render strict report"| Report
    Ledger -.->|"doctor audits integrity"| Doctor
    Doctor -->|"issue found"| Claude
    Doctor -->|"clean"| Done
    Report --> Done
```
