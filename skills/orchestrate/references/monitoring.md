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
`branch` when present before launch. Capture stdout as `events.jsonl` and the last message as
`handoff.md`. Resolve the recorded Git values from the same path passed to `-C`:

```bash
git -C <worktree> rev-parse --show-toplevel
git -C <worktree> rev-parse HEAD
git -C <worktree> branch --show-current
```

Prepare each execution in this exact order: create the `execution-NN` directory, write
`prompt.md`, create an empty `events.jsonl`, append the journal `execution` entry, then launch.
The events file therefore exists before the journal or monitor refers to it, and an execution
that dies at launch still leaves a well-formed record.

Then launch Codex detached in its own process group, with every shell redirect target written as
a literal absolute path (a `$VAR`, `~`, or relative path in redirect position risks truncating
the wrong file when the shell environment differs from the one that composed the command):

```bash
set -m
nohup codex exec --json \
  --output-last-message /abs/run-dir/codex-impl-01/execution-01/handoff.md \
  -s workspace-write -c approval_policy=never -C <worktree> \
  - \
  < /abs/run-dir/codex-impl-01/execution-01/prompt.md \
  > /abs/run-dir/codex-impl-01/execution-01/events.jsonl &
launch_pid=$!
disown "$launch_pid"
launch_pgid="$(ps -o pgid= -p "$launch_pid" | tr -d ' ')"
{
  printf '%s\n' "$launch_pid"
  printf '%s\n' "$launch_pgid"
  date -u '+%Y-%m-%dT%H:%M:%SZ'
} > /abs/run-dir/codex-impl-01/execution-01/pid
```

`set -m` gives the launch its own process group (`setsid` is an equivalent where available). The
three-line `pid` sidecar (PID, PGID, UTC launch timestamp) is what later liveness checks use, so
write it immediately after launch and before arming the monitor. Detachment keeps the agent
independent of the orchestrating session: a harness-managed background task dies with its
session, and a long execution must not.

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
codex exec -s workspace-write -c approval_policy=never \
  resume --json \
  --output-last-message /abs/run-dir/codex-impl-01/execution-02/handoff.md \
  <session-id> - \
  < /abs/run-dir/codex-impl-01/execution-02/prompt.md \
  > /abs/run-dir/codex-impl-01/execution-02/events.jsonl
```

Do not pass `-C` together with `resume`: the resumed session inherits its working directory
from the original launch, and current Codex CLI releases reject the combination.
Read the absolute `worktree` from the preceding execution record instead, and verify it still
exists before resuming. Inspect its current HEAD and branch and record them in the new execution; the prior
`head` is a snapshot, so do not check out or reset to it merely because the worktree advanced.
Resume degrades when the original session state has been pruned or the CLI version changed since
the launch — treat a resume that starts but recognizes nothing as a failed resume and fall back
to a fresh session rather than re-prompting it. A fresh native session requires a new named
agent. The resumed command still follows the same preparation order, literal absolute redirect
paths, detachment, and `pid` sidecar as a fresh launch.

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

The monitor is read-only and emits completion, failure, unknown-format, missing-stream, or stale
notifications. A stale or unknown target is terminal to that monitor invocation: the monitor has
stopped watching it even though the underlying execution may still be running. While any
execution remains in flight, re-arm the monitor no later than 60 minutes after its last arm or
exit so a long-running agent is never unwatched indefinitely.

Treat silence and staleness as ambiguous. On `codex_agent_stale`, before appending any
`execution_result`:

1. Check the `events.jsonl` mtime for progress after the notification.
2. Read PID and PGID from the execution's `pid` sidecar and check them with `ps` rather than
   guessing from process names.
3. Inspect the handoff and the assigned worktree for completed or partial work.

Never conclude failure from staleness alone. If the process group is still alive, append no
result and re-arm the monitor. After a machine-sleep gap — a wall-clock jump beyond the stale
threshold — run `state` for every in-flight target before trusting any stale notification
emitted across the gap, because staleness computed over a sleep period reflects the clock, not
the agent.

On `codex_agent_unknown`, run `state --dump-event-types` for that target. Do not infer whether
the agent is running, passed, or failed from a stream the parser does not recognize; surface the
incompatibility and the observed event types to the user before deciding how to proceed.
