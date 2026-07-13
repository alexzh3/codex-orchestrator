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
`branch` when present before launch. The runner sends the saved prompt to Codex, captures raw
stdout as `events.jsonl`, and lets Codex save the last message as `handoff.md`. Resolve the
recorded Git values from the same path passed to `-C`:

```bash
git -C <worktree> rev-parse --show-toplevel
git -C <worktree> rev-parse HEAD
git -C <worktree> branch --show-current
```

Then launch Codex:

```bash
EXECUTION_DIR=".codex-orchestrator/runs/<run-id>/codex-impl-01/execution-01"
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/codex_orch_tools.py" run \
  --label codex-impl-01 \
  --events "$EXECUTION_DIR/events.jsonl" \
  --prompt "$EXECUTION_DIR/prompt.md" \
  -- codex exec --json --output-last-message "$EXECUTION_DIR/handoff.md" \
     -s workspace-write -c approval_policy=never -C <worktree> -
```

Launch the runner as a Claude Code background Bash task. It creates `events.jsonl` exclusively,
aborting before Codex starts if that file already exists, then captures raw Codex stdout there
byte-for-byte. Its own stdout contains compact one-line progress for the human `/tasks` view.
Those lines are not a Claude monitor stream: Claude keeps using `state` and `monitor` and receives
only completion, failure, stale, missing-stream, or incompatible-format notifications. Codex
stderr passes through for native diagnostics. After a clean capture, the runner exits with Codex's
exit code. Capture, prompt, or launch failures exit nonzero; cancellation exits with 128 plus the
signal number. Everything after `--` passes to Codex unchanged, including fresh, resume, and
review commands.

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
  --events "$EXECUTION_DIR/events.jsonl" \
  --prompt "$EXECUTION_DIR/prompt.md" \
  -- codex exec -C <worktree> -s workspace-write -c approval_policy=never \
     resume --json --output-last-message "$EXECUTION_DIR/handoff.md" \
     <session-id> -
```

Read the absolute `worktree` from the preceding execution and use it with `-C` and the same
`session_id`. Inspect its current HEAD and branch and record them in the new execution; the prior
`head` is a snapshot, so do not check out or reset to it merely because the worktree advanced. Use
an absolute `EXECUTION_DIR` when the shell runs elsewhere. A fresh native session requires a new
named agent.

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
stale notifications. Treat silence and staleness as ambiguous; inspect the handoff and repository
before appending `execution_result`.
