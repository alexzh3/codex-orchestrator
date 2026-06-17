# Gate Compute

Use this command before handing off shared GPU, Docker, Isaac, Kit, or training work.

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
