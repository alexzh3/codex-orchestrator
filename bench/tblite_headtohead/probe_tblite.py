#!/usr/bin/env python3
"""Drive ONE real TBLite task through the codex-orchestrator adapter (paid run).

Persistent jobs dir + on-failure diagnostics so one run is fully inspectable.
Usage: probe_tblite.py [task_id] [plugin_ref]
"""
import json
import os
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts"))

os.environ.setdefault("CODEX_ORCH_CLAUDE_AUTH_MODE", "credentials")
os.environ.setdefault("CODEX_FORCE_AUTH_JSON", "1")
os.environ["ANTHROPIC_API_KEY"] = ""

from bench.adapters.tblite import TBLiteAdapter  # noqa: E402

task_id = sys.argv[1] if len(sys.argv) > 1 else "book-portfolio-analysis"
plugin_ref = sys.argv[2] if len(sys.argv) > 2 else "HEAD"

# PERSISTENT work dir so harbor result.json + claude-code.txt survive for inspection.
work_dir = HERE / "work" / f"{task_id}__{plugin_ref.replace('/', '_')}"
work_dir.mkdir(parents=True, exist_ok=True)

task = {"id": task_id, "prompt": "", "selection": "probe", "timeout_seconds": 3600}
adapter = TBLiteAdapter()


def dump_diagnostics() -> None:
    print("\n=== DIAGNOSTICS (harbor artifacts) ===")
    results = sorted(work_dir.rglob("result.json"))
    for rp in results:
        try:
            o = json.loads(rp.read_text())
        except Exception as e:
            print(f"  {rp}: unreadable ({e})")
            continue
        if not ("trial_name" in o and "task_name" in o):
            continue  # skip job-level summary
        print(f"\n-- trial result: {rp}")
        for k in ("exception_info", "verifier_result", "agent_result",
                  "environment_setup", "agent_setup", "agent_execution"):
            if k in o:
                print(f"   {k} = {json.dumps(o[k])[:500]}")
    trajs = sorted(work_dir.rglob("claude-code.txt"))
    for tp in trajs:
        lines = tp.read_text(errors="replace").splitlines()
        print(f"\n-- trajectory: {tp} ({len(lines)} lines) — last 40:")
        for ln in lines[-40:]:
            print("   " + ln[:400])
    logs = sorted(work_dir.rglob("trial.log"))
    for lp in logs:
        lines = lp.read_text(errors="replace").splitlines()
        print(f"\n-- trial.log: {lp} — last 30:")
        for ln in lines[-30:]:
            print("   " + ln[:300])


start = time.monotonic()
try:
    result = adapter.run_task(
        task, plugin_ref, dry_run=False, repo_root=REPO, work_dir=work_dir
    )
except Exception as exc:
    print(f"run_task raised: {type(exc).__name__}: {exc}")
    dump_diagnostics()
    print(f"\nwall_seconds={round(time.monotonic()-start,1)}  jobs_dir={work_dir}")
    sys.exit(1)

wall = time.monotonic() - start
ext = result.get("external_score", {}) or {}
tb = ext.get("token_breakdown", {}) or {}

# Session/rate limit or any run where Claude produced 0 tokens is NOT a real
# result — do not write an artifact (so the matrix reruns it), fail loudly.
_cl = tb.get("claude") or {}
if ((_cl.get("input_tokens") or 0) + (_cl.get("output_tokens") or 0)) == 0:
    print("=== SESSION_LIMIT_OR_NO_RUN: Claude produced 0 tokens; artifact NOT written ===")
    print("exception:", json.dumps(ext.get("exception"))[:300])
    sys.exit(2)
summary = {
    "task_id": task_id, "plugin_ref": plugin_ref,
    "passed": result.get("passed"), "report_score": result.get("report_score"),
    "real_orchestration": ext.get("real_orchestration"),
    "codex_sessions": result.get("codex_sessions"),
    "degenerate_no_codex": ext.get("degenerate_no_codex", False),
    "token_note": ext.get("token_note"),
    "tokens_claude": tb.get("claude"), "tokens_gpt": tb.get("gpt"),
    "tokens_combined": tb.get("combined"),
    "wall_seconds": round(wall, 1),
}
print("=== PROBE SUMMARY ===")
print(json.dumps(summary, indent=2, default=str))
out = HERE / "artifacts"
out.mkdir(parents=True, exist_ok=True)
dest = out / f"probe-{task_id}-{plugin_ref.replace('/', '_')}.json"
dest.write_text(json.dumps(result, indent=2, default=str), encoding="utf-8")
print(f"\nfull result -> {dest}")
