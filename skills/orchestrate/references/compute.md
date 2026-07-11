# Parallel Work And Compute

## Parallel Work

Before parallel execution, compare the active tasks' declared `files` and shared resources:

- Disjoint lists may run concurrently in the same repository when tools will not mutate shared
  generated files.
- Overlapping paths or shared contracts require sequential handoff or separate worktrees.
- Shared build outputs, databases, ports, GPUs, and evidence paths also count as conflicts.

An independent `--uncommitted` review reserves its task's `files` and shared resources until its
handoff or terminal blocked/failed outcome is recorded. Disjoint work may continue; otherwise use a
separate worktree or committed snapshot.

Use native Git worktrees for isolation:

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

Check utilization, processes, memory, disk, ports, and task outputs. Record a decision when resource
state changes execution timing, isolation, or acceptance.
