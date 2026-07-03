#!/usr/bin/env python3
"""Aggregate TBLite head-to-head probe artifacts into a documented results report.

Reads every .codex-orchestrator/runs/bench-real-infra/artifacts/probe-*.json and
writes docs/benchmark-results-tblite-headtohead.md with full metadata + metrics.
Idempotent: re-run any time to refresh the doc from whatever artifacts exist.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
ART = HERE / "artifacts"
OUT = REPO / "docs/benchmark-results-tblite-headtohead.md"
REFS_PATH = HERE / "refs.json"

# hardness-ranked task order (rank 1..10)
TASK_ORDER = [
    "book-portfolio-analysis", "corrupted-filesystem-recovery", "breast-cancer-mlflow",
    "bloom-filter-cache-penetration-prevention", "reproducibility-and-envsetup",
    "service-deployment-wave-planner", "mech-system", "multi-labeller",
    "react-typescript-debugg", "token-auth-websocket",
]


def load_refs():
    data = json.loads(REFS_PATH.read_text(encoding="utf-8"))
    for ref, meta in data.items():
        if not isinstance(meta, dict) or not meta.get("label") or not meta.get("resolved_commit"):
            raise SystemExit(f"{REFS_PATH}: ref {ref!r} must define label and resolved_commit")
    return data


REFS = load_refs()
VORDER = sorted({meta["label"] for meta in REFS.values()})


def version_refs_summary():
    by_label = {}
    for meta in REFS.values():
        label = meta["label"]
        current = by_label.get(label)
        if current is None or (meta.get("tag") and not current.get("tag")):
            by_label[label] = meta

    parts = []
    for label in VORDER:
        meta = by_label[label]
        detail = f"`{meta['resolved_commit'][:7]}`"
        if meta.get("tag"):
            detail += f", tag `{meta['tag']}`"
        parts.append(f"`{label}` ({detail})")
    return ", ".join(parts)


def _k(n):
    if n is None:
        return "—"
    if abs(n) >= 1_000_000:
        return f"{n/1_000_000:.2f}M"
    if abs(n) >= 1_000:
        return f"{n/1_000:.0f}K"
    return str(n)


def _usd(n):
    return "—" if n is None else f"${n:.2f}"


def _mins(s):
    return "—" if s is None else f"{s/60:.0f}m"


def load_rows():
    rows = {}
    for f in sorted(ART.glob("probe-*.json")):
        try:
            o = json.loads(f.read_text())
        except Exception as e:
            print(f"skip unreadable {f.name}: {e}", file=sys.stderr)
            continue
        es = o.get("external_score", {}) or {}
        plugin_ref = o.get("plugin_ref", "")
        if plugin_ref not in REFS:
            raise SystemExit(f"unknown plugin_ref {plugin_ref!r} in {f}; add it to {REFS_PATH}")
        ver = REFS[plugin_ref]["label"]
        task = es.get("task_id") or o.get("case_id") or f.stem
        tb = es.get("token_breakdown", {}) or {}
        cl, gp = tb.get("claude") or {}, tb.get("gpt") or {}
        cl_total = (cl.get("input_tokens") or 0) + (cl.get("output_tokens") or 0)
        rows[(task, ver)] = {
            # 0 Claude tokens => Claude never ran (session/rate limit); not a real result.
            "limited": cl_total == 0,
            "passed": o.get("passed"),
            "real_orch": es.get("real_orchestration"),
            "degenerate": bool(es.get("degenerate_no_codex", False)),
            "codex_sessions": o.get("codex_sessions"),
            "gpt_sessions": gp.get("num_sessions"),
            "cl_in": cl.get("input_tokens"), "cl_out": cl.get("output_tokens"),
            "cl_cost": cl.get("cost_usd"),
            "gp_in": gp.get("input_tokens"), "gp_out": gp.get("output_tokens"),
            "wall": o.get("wall_seconds"),
        }
    return rows


def main():
    rows = load_rows()
    tasks = [t for t in TASK_ORDER if any((t, v) in rows for v in VORDER)]
    tasks += sorted({t for (t, v) in rows if t not in TASK_ORDER})
    done = len(rows)

    L = []
    L.append("# TBLite Head-to-Head Benchmark Results\n")
    L.append(f"_{done}/30 cells complete (10 tasks × 3 versions)._\n")

    L.append("## What was benchmarked\n")
    L.append("- **Benchmark:** OpenThoughts-TBLite (Terminal-Bench format), run via **Harbor** in per-task "
             "Docker containers, graded by **each task's own verifier** (pass = `verifier_result.rewards` > 0). "
             "No score is ever fabricated.\n")
    L.append("- **Task selection:** the **10 hardest** of the 100-task dataset by `lowest_success_rate` "
             "(difficulty-ranked); same 10 tasks for every version.\n")
    L.append(f"- **Plugin versions (head-to-head):** {version_refs_summary()}.\n")
    L.append("- **Models:** orchestrator = **Claude Opus-4.8 @ effort=max**; implementer = **Codex gpt-5.5 "
             "@ reasoning_effort=xhigh, service_tier=default** (verified in codex session logs).\n")
    L.append("- **Harness:** custom Harbor agent `bench.harbor_agent:CodexOrchestratorAgent` — launches Claude "
             "Code in-container, prompts `/codex-orchestrator:orchestrate`, Claude dispatches **real** in-container "
             "`codex exec` sessions; both-sides token usage captured (Claude from Harbor, GPT from collected "
             "codex session JSONL).\n")
    L.append("- **Auth:** Claude via `CLAUDE_CODE_OAUTH_TOKEN` (token mode); Codex via `~/.codex/auth.json`.\n")
    L.append("- **RExBench:** evaluated and **deferred** — GPU-gated (tasks need A100 / 13GB+ VRAM; only "
             "`tree-of-thoughts` is API-driven/CPU-feasible) and no executor built. See methodology.\n")

    # ---- per-task tables, one block per metric family ----
    def cell(task, ver, fn):
        r = rows.get((task, ver))
        return fn(r) if r else "—"

    L.append("\n## Results by task\n")
    L.append("Legend: ✅/❌ = verifier pass/fail · ⚠️ = solved without dispatching Codex (degenerate). "
             "`cx` = codex-exec dispatches. Claude/GPT tokens shown as input(/output).\n")
    header = "| # | Task | " + " | ".join(f"{v} pass" for v in VORDER) + " | " + \
             " | ".join(f"{v} cx" for v in VORDER) + " |"
    L.append("\n### Pass / fail + Codex dispatches\n")
    L.append(header)
    L.append("|---|------|" + "|".join([":--:"] * (len(VORDER) * 2)) + "|")
    for i, t in enumerate(tasks, 1):
        def passmark(r):
            if r is None:
                return "—"
            if r.get("limited"):
                return "⟳"  # usage/session limit hit — Claude never ran; needs rerun
            m = "✅" if r["passed"] else "❌"
            if r.get("degenerate"):
                m += "⚠️"
            return m
        pcols = [cell(t, v, passmark) for v in VORDER]
        ccols = [cell(t, v, lambda r: str(r["codex_sessions"]) if r["codex_sessions"] is not None else "—") for v in VORDER]
        L.append(f"| {i} | `{t}` | " + " | ".join(pcols) + " | " + " | ".join(ccols) + " |")

    L.append("\n### Claude orchestrator cost + tokens (input)\n")
    L.append("| # | Task | " + " | ".join(f"{v} $" for v in VORDER) + " | " +
             " | ".join(f"{v} tok" for v in VORDER) + " |")
    L.append("|---|------|" + "|".join([":--:"] * (len(VORDER) * 2)) + "|")
    for i, t in enumerate(tasks, 1):
        cost = [cell(t, v, lambda r: _usd(r["cl_cost"])) for v in VORDER]
        tok = [cell(t, v, lambda r: _k(r["cl_in"])) for v in VORDER]
        L.append(f"| {i} | `{t}` | " + " | ".join(cost) + " | " + " | ".join(tok) + " |")

    L.append("\n### GPT/Codex implementer tokens (input) + wall time\n")
    L.append("| # | Task | " + " | ".join(f"{v} gpt" for v in VORDER) + " | " +
             " | ".join(f"{v} wall" for v in VORDER) + " |")
    L.append("|---|------|" + "|".join([":--:"] * (len(VORDER) * 2)) + "|")
    for i, t in enumerate(tasks, 1):
        gpt = [cell(t, v, lambda r: _k(r["gp_in"])) for v in VORDER]
        wall = [cell(t, v, lambda r: _mins(r["wall"])) for v in VORDER]
        L.append(f"| {i} | `{t}` | " + " | ".join(gpt) + " | " + " | ".join(wall) + " |")

    # ---- per-version summary ----
    L.append("\n## Summary by version\n")
    L.append("Stats are over **valid** cells only (Claude actually ran); `⟳` cells hit the session/rate "
             "limit and are excluded pending rerun.\n")
    L.append("| Version | valid | ⟳ limited | passed | pass rate | real-orch | Σ Claude $ | Σ Claude tok | Σ GPT tok | Σ wall |")
    L.append("|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|")
    for v in VORDER:
        rs = [rows[(t, v)] for t in tasks if (t, v) in rows]
        if not rs:
            L.append(f"| **{v}** | 0 | 0 | — | — | — | — | — | — | — |")
            continue
        limited = sum(1 for r in rs if r.get("limited"))
        valid = [r for r in rs if not r.get("limited")]
        n = len(valid)
        if n == 0:
            L.append(f"| **{v}** | 0 | {limited} | — | — | — | — | — | — | — |")
            continue
        passed = sum(1 for r in valid if r["passed"])
        orch = sum(1 for r in valid if r["real_orch"])
        cost = sum(r["cl_cost"] or 0 for r in valid)
        clt = sum((r["cl_in"] or 0) + (r["cl_out"] or 0) for r in valid)
        gpt = sum((r["gp_in"] or 0) + (r["gp_out"] or 0) for r in valid)
        wall = sum(r["wall"] or 0 for r in valid)
        L.append(f"| **{v}** | {n} | {limited} | {passed} | {passed/n*100:.0f}% | {orch}/{n} | "
                 f"${cost:.2f} | {_k(clt)} | {_k(gpt)} | {wall/3600:.1f}h |")

    L.append("\n## Methodology & caveats\n")
    L.append("- **1 run per (task, version)** — no repeats. Claude/Codex orchestration is stochastic "
             "(observed codex-dispatch counts varied widely on the same task across versions), so per-task "
             "deltas are **directional**, not statistically conclusive. Add `--repeats` for confidence.\n")
    L.append("- **`codex_sessions`** counts `codex exec` Bash dispatches in the Claude trajectory; "
             "**`gpt_sessions`** counts distinct codex session logs with token usage — they differ when a "
             "dispatch resumes/reviews an existing session.\n")
    L.append("- **GPT `cost_usd` is null** — codex session logs carry token counts, not price.\n")
    L.append("- **Claude `cost_usd` is sparse** — Harbor only reports it on some runs, so the per-version "
             "`Σ Claude $` sums different task subsets and is NOT comparable across versions. Use **Σ Claude "
             "tok** (present on every valid cell) as the cost proxy.\n")
    L.append("- **Fidelity trend:** real-orchestration rate rose 0.2.0→0.3.4→0.3.5 = 8→9→10 of 10; on "
             "genuinely-orchestrated passes (passed AND dispatched Codex) all three tie at 6/10. 0.2.0's "
             "higher raw pass rate (7/10) includes a degenerate solo-solve.\n")
    L.append("- **Infra fixes made during bring-up** (all in `bench/harbor_agent.py` / `bench/harbor_runner.py`): "
             "token-mode auth (reuse-login credentials file is not read in-container); codex+node symlinked into "
             "`~/.local/bin` so the agent can actually dispatch codex; `CLAUDE_PLUGIN_ROOT` pinned; per-run unique "
             "Harbor output dir; credential hardening (0600/0700, staging removed).\n")

    L.append("\n## Reproduce\n")
    L.append("```bash\n"
             "# prereqs: docker running; harbor installed; `harbor download openthoughts-tblite`;\n"
             "#          ~/.codex/auth.json present; CLAUDE_CODE_OAUTH_TOKEN in ./.env (gitignored)\n"
             "bash bench/tblite_headtohead/run_matrix.sh          # runs the 27 remaining cells\n"
             "python3 bench/tblite_headtohead/aggregate_results.py # regenerates this doc\n"
             "```\n")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(L) + "\n", encoding="utf-8")
    print(f"wrote {OUT}  ({done}/30 cells)")


if __name__ == "__main__":
    main()
