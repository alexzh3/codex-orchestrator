# Agent Identity, Parallel Work, And Compute

## Identity And Reuse

Treat each named agent as a persistent execution context with a provider, primary role, native
`session_id`, repository/worktree, and execution history. Continue in the same native session when
its context remains relevant. If its context is nearly full, summarize the goal, files touched,
decisions, check state, unresolved issues, and next request before resuming it.

Create a fresh agent only for contextually unrelated work, required isolation, an unusable session
after bounded inspection, or an explicit user request. A new rollout file or new execution does not
by itself create a new agent.

## Parallel Work

Every active task declares its allowed/owned file paths or globs in `files`. This is the planned
boundary; an execution result's `files_changed` is Claude's compact attribution note, while the
repository diff determines what actually changed. Before parallel execution, compare the task
`files` lists:

- Disjoint lists may run concurrently in the same repository when tools will not mutate shared
  generated files.
- Overlapping paths or shared contracts require sequential handoff or separate worktrees.
- Shared build outputs, databases, ports, GPUs, and evidence paths also count as conflicts.

Use native Git for isolation; the plugin has no worktree protocol command:

```bash
git worktree add ../<repo>-codex-impl-01 -b codex-impl-01
git worktree list
```

Do not merge or remove a worktree until its execution has stopped, its handoff is saved, and Claude
has inspected the diff.

## Compute Gating

Check scarce resources before expensive local tests or research workloads:

```bash
nvidia-smi --query-gpu=memory.used,memory.total,utilization.gpu --format=csv,noheader
nvidia-smi --query-compute-apps=pid,used_memory --format=csv,noheader
pgrep -af 'isaac|kit|python.sh|pytest' | grep -v codex
docker ps --format '{{.Names}} {{.Status}}'
free -g
df -h /
```

`docker ps` showing `Up` is not proof of active compute. Check utilization, processes, memory, disk,
ports, and task-specific outputs. Record a material compute decision in the ledger when it changes
execution timing, isolation, or acceptance.
