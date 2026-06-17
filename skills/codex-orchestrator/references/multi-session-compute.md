# Multi-Session And Compute Reference

Use this when coordinating multiple Codex sessions, preparing handoffs, or checking shared compute.

## Parallel Sessions

Parallel sessions must use separate git worktrees unless the user explicitly chooses same-worktree
coordination:

```bash
git worktree add ../repo-codex-a -b codex/a main
git worktree add ../repo-codex-b -b codex/b main
```

Helper:

```bash
python3 scripts/codex_orch_worktree.py --name codex-a
```

Parallel work is appropriate when scopes do not conflict and sessions do not compete for scarce
compute. Assign non-overlapping goals, file scopes, artifact paths, and output directories. Track
each thread id and rollout path separately.

## Sequential Handoff

Use sequential coordination when a compute gate is required, agents would touch the same
files/contracts, or the user asks for serial handoff.

Before triggering the next session:

1. Wait for the current goal to complete and finish review.
2. Verify the next session plan against the codebase.
3. Run the compute gate when shared GPU, Isaac, Kit, Docker, training, or disk-heavy artifacts may be
   involved.
4. Trigger Codex with a tightly scoped `codex exec` or `codex exec resume` prompt.
5. Re-arm monitoring for the new or resumed session.

## Compute Gate

Codex should self-gate expensive work, and Claude should gate at handoffs or whenever unsure whether
resources are free:

```bash
nvidia-smi --query-gpu=memory.used,memory.total,utilization.gpu --format=csv,noheader
nvidia-smi --query-compute-apps=pid,used_memory --format=csv,noheader
pgrep -af 'isaac|kit|python.sh|pytest' | grep -v codex
docker ps --format '{{.Names}} {{.Status}}'
free -g
df -h /
```

A container being `Up` does not mean it is busy. Check VRAM, GPU utilization, and compute apps. No
compute apps plus low utilization means it is usually safe to hand off. Watch disk because video and
HDF5 artifacts can fill the filesystem quickly.

`run_docker.sh` is often interactive (`--rm --tty`). For headless automation, start a detached
container deliberately instead of assuming an interactive script will work unattended.
