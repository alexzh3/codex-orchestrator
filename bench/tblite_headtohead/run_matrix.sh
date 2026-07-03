#!/usr/bin/env bash
# TBLite head-to-head matrix: 9 hardest tasks (ranks 2-10) x 3 plugin versions.
# Resumable: skips any (task, ref) whose artifact already exists. Robust: a run
# that fails does not abort the matrix (its per-run log keeps the diagnostics).
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$HERE/../.." && pwd)"
cd "$REPO" || exit 2
PROBE="$HERE/probe_tblite.py"
ART="$HERE/artifacts"
LOGDIR="$HERE/matrix-logs"
mkdir -p "$ART" "$LOGDIR"

# Claude auth: reuse the operator token from .env, token mode (credentials-file
# reuse does not authenticate in-container; see benchmark docs).
set -a; . "$REPO/.env" 2>/dev/null; set +a
export CODEX_ORCH_CLAUDE_AUTH_MODE=token

TASKS=(
  corrupted-filesystem-recovery
  breast-cancer-mlflow
  bloom-filter-cache-penetration-prevention
  reproducibility-and-envsetup
  service-deployment-wave-planner
  mech-system
  multi-labeller
  react-typescript-debugg
  token-auth-websocket
)
REFS=(v0.2.0 release/0.3.4 v0.3.5)

total=$(( ${#TASKS[@]} * ${#REFS[@]} ))
n=0
echo "MATRIX_START $(date '+%Y-%m-%d %H:%M:%S %Z')  total=$total"
for task in "${TASKS[@]}"; do
  for ref in "${REFS[@]}"; do
    n=$((n+1))
    safe=$(echo "$ref" | tr '/' '_')
    artifact="$ART/probe-${task}-${safe}.json"
    tag="[$n/$total] task=$task ref=$ref"
    if [ -f "$artifact" ]; then
      echo "SKIP  $tag (artifact exists) $(date '+%H:%M:%S')"
      continue
    fi
    echo ">>>>> RUN  $tag  $(date '+%H:%M:%S')"
    python3 "$PROBE" "$task" "$ref" > "$LOGDIR/${task}__${safe}.log" 2>&1
    rc=$?
    if [ -f "$artifact" ]; then
      echo "<<<<< DONE $tag exit=$rc (artifact written) $(date '+%H:%M:%S')"
    else
      echo "!!!!! FAIL $tag exit=$rc (no artifact; see log) $(date '+%H:%M:%S')"
    fi
  done
done
echo "MATRIX_COMPLETE $(date '+%Y-%m-%d %H:%M:%S %Z')"
