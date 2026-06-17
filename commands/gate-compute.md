---
description: Check shared GPU, Docker, Isaac, Kit, and training resources before dispatching expensive Codex work.
---

# Gate Compute

Use this command before handing off shared GPU, Docker, Isaac, Kit, or training work.

Use when: the next Codex step may use scarce local compute, containers, simulators, or large artifact
storage and you need a handoff safety check.

Do not use when: the next step is ordinary code review or a lightweight test command with no shared
compute contention.

Default checks:

```bash
nvidia-smi --query-gpu=memory.used,memory.total,utilization.gpu --format=csv,noheader
nvidia-smi --query-compute-apps=pid,used_memory --format=csv,noheader
pgrep -af 'isaac|kit|python.sh|pytest' | grep -v codex
docker ps --format '{{.Names}} {{.Status}}'
free -g
df -h /
```

Follow `skills/codex-orchestrator/SKILL.md` section 7 for interpretation and handoff policy.
