# Parallel Work And Compute

## Parallel Work

Before parallel execution, compare the active tasks' declared `files` and shared resources:

- Disjoint lists may run concurrently in the same repository when tools will not mutate shared
  generated files.
- Overlapping paths or shared contracts require sequential handoff or separate worktrees.
- Shared build outputs, databases, ports, GPUs, and evidence paths also count as conflicts.

Review a committed SHA when possible. For an uncommitted target, reserve only its task's `files` and
shared resources until the review ends. Disjoint work may continue; otherwise use a separate
worktree or committed snapshot.

Use native Git worktrees for isolation:

```bash
git worktree add ../<repo>-codex-impl-01 -b codex-impl-01
git worktree list
```

Do not merge or remove a worktree until its execution has stopped, its handoff is saved, and Claude
has inspected the diff.

## Compute Gating

Before expensive local tests or research workloads, inspect only the processes, compute, memory,
disk, ports, or services that the task actually depends on. Record a decision when resource state
changes execution timing, isolation, or acceptance.
