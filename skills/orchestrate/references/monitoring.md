# Monitoring Codex Agents

Use the bundled tools for compact status snapshots. They parse event streams locally; do not copy
raw logs into Claude's context unless a focused inspection is needed for an ambiguous or failed
agent.

## Headless Codex

Create the next numbered execution under its named agent:

```text
codex-impl-01/execution-01/
  prompt.md
  events.jsonl
  handoff.md
```

Save `prompt.md` and append `execution` with the absolute `worktree`, full `head`, and attached
`branch` when present before launch. With an active role configuration, record one selected
concrete `effort` plus any `model` and `service_tier` supplied by the resolved policy. The runner
sends the saved prompt to Codex, captures raw stdout as `events.jsonl`, and lets Codex save the
last message as `handoff.md`. Resolve the recorded Git values from the same path passed to `-C`:

```bash
git -C <worktree> rev-parse --show-toplevel
git -C <worktree> rev-parse HEAD
git -C <worktree> branch --show-current
```

Prepare each execution in this exact order: create the `execution-NN` directory, write `prompt.md`,
append the journal `execution` entry, then launch. The runner owns `events.jsonl` and refuses to
start if it already exists, so do not pre-create it. An execution that dies at launch therefore
still leaves a well-formed record.

Then launch Codex: this example uses an active role configuration; select the effort from the
resolved `implementation` policy:

```bash
EXECUTION_DIR=".codex-orchestrator/runs/<run-id>/codex-impl-01/execution-01"
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/codex_orch_tools.py" run \
  --label codex-impl-01 \
  --repo <repo> \
  --role implementation \
  --reasoning-effort xhigh \
  --events "$EXECUTION_DIR/events.jsonl" \
  --prompt "$EXECUTION_DIR/prompt.md" \
  -- codex exec --json --output-last-message "$EXECUTION_DIR/handoff.md" \
     -s workspace-write -c approval_policy=never -C <worktree> -
```

Launch the runner under the SKILL's Background Launch Invariant. It validates configured execution
inputs before reading the prompt, creating `events.jsonl`, or starting Codex. For an active policy
it injects
`--model <configured-model>` when present and the selected `model_reasoning_effort`;
configured `speed = default` injects `service_tier="default"`, while `speed = fast` injects
`service_tier="fast"` and the Fast-mode feature flag. It rejects conflicting child performance
flags, so do not add those flags manually. If
`.codex-orchestrator/config.ini` is absent, keep `--repo` and `--role`, omit
`--reasoning-effort`, and everything after `--` passes to Codex byte-for-byte so native Codex
configuration remains authoritative. Supplying an effort without the file is an error.

The runner creates `events.jsonl` exclusively, aborting before Codex starts if that file already
exists, then captures raw Codex stdout there byte-for-byte. Its own stdout contains timestamped
progress for the human `/tasks` view. Commands appear without a `command started:` prefix, followed
on completion by bounded, scrubbed output without a `command completed` line. Terminal redraws are
collapsed to their latest state; long output keeps its first and last eight lines around an omission
marker. Failed commands append `command failed` with `exit=N` when available. Those lines are not a
Claude monitor stream: Claude keeps using `state` and `monitor` and receives only completion,
failure, stale, missing-stream, or incompatible-format notifications. Codex stderr passes through
for native diagnostics. After a clean capture, the runner exits with Codex's exit code. Capture,
prompt, configuration, or launch failures exit nonzero; cancellation exits with 128 plus the signal
number. Do not retry a rejected configured model or Fast tier at a lower setting without changing
the policy explicitly.

Never use `--ephemeral`. Use broad access only with explicit authorization and isolation.

Require Codex to end every execution with this concise handoff shape:

```markdown
## Status

## Summary

## Files Changed

## Claims / Findings

## Commands Reported

## Caveats / Blockers
```

Extract the last completed agent message from events only when normal handoff capture failed.

Resume a relevant idle session as the next execution under the same agent:

```bash
EXECUTION_DIR=".codex-orchestrator/runs/<run-id>/codex-impl-01/execution-02"
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/codex_orch_tools.py" run \
  --label codex-impl-01 \
  --repo <repo> \
  --role implementation \
  --reasoning-effort max \
  --events "$EXECUTION_DIR/events.jsonl" \
  --prompt "$EXECUTION_DIR/prompt.md" \
  -- codex exec -s workspace-write -c approval_policy=never \
     resume --json --output-last-message "$EXECUTION_DIR/handoff.md" \
     <session-id> -
```

Do not pass `-C` together with `resume`: the resumed session inherits its working directory from
the original launch, and current Codex CLI releases reject the combination. Everything after `--`
reaches Codex byte-for-byte, so the runner does not shield a `-C` added here.
Read the absolute `worktree` from the preceding execution record instead, and verify it still
exists before resuming. Inspect its current HEAD and branch and record them in the new execution;
the prior `head` is a snapshot, so do not check out or reset to it merely because the worktree
advanced. Use an absolute `EXECUTION_DIR` when the shell runs elsewhere. Reselect effort for this
execution from its current difficulty, breadth, and context instead of copying the previous value.
When role configuration is absent, omit the example's `--reasoning-effort max`.

Resume degrades when the original session state has been pruned or the CLI version changed since
the launch — treat a resume that starts but recognizes nothing as a failed resume and fall back to
a fresh session rather than re-prompting it. A fresh native session requires a new named agent.

## Agent State And Monitor

Use `state` for a compact agent snapshot:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/codex_orch_tools.py" state <session-id> \
  --file <events-jsonl> --json
```

After context loss, call `state` again. Do not persist parser positions in the journal.

Monitor an active run or explicit stream:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/codex_orch_tools.py" monitor \
  --repo <repo> --run-id <run-id>
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/codex_orch_tools.py" monitor \
  --log <events-jsonl> --fail-on-agent-failure
```

Always select the target with `--run-id` plus its repository or with `--log`.

The monitor is read-only and emits completion, failure, incompatible-format, missing-stream, or
stale notifications. A stale or incompatible-format target is terminal to that monitor invocation:
the monitor has stopped watching it even though the underlying execution may still be running.
While any execution remains in flight, re-arm the monitor no later than 60 minutes after its last
arm or exit so a long-running agent is never unwatched indefinitely.

Treat silence and staleness as ambiguous. On `codex_agent_stale`, before appending any
`execution_result`:

1. Check the `events.jsonl` mtime for progress after the notification.
2. Check the agent's registered background task in `/tasks` — the launch invariant names it for
   the exact agent — rather than guessing from process names.
3. Inspect the handoff and the assigned worktree for completed or partial work.

Never conclude failure from staleness alone. If the task is still running, append no result and
re-arm the monitor. After a machine-sleep gap — a wall-clock jump beyond the stale threshold — run
`state` for every in-flight target before trusting any stale notification emitted across the gap,
because staleness computed over a sleep period reflects the clock, not the agent.

On `codex_agent_unknown`, run `state --dump-event-types` for that target. Do not infer whether the
agent is running, passed, or failed from a stream the parser does not recognize; surface the
incompatibility and the observed event types to the user before deciding how to proceed.
