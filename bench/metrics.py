from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from codex_orchestrator.report import (  # noqa: E402
    is_final_review_verification,
    prompt_log_pairs_complete as core_prompt_log_pairs_complete,
    report_completeness_score,
    score_total,
)


def report_score(state: dict[str, object], ledger: list[dict[str, object]]) -> float:
    """Return the core deterministic report completeness score."""
    return score_total(report_completeness_score(state, ledger))


def task_count(ledger: list[dict[str, object]]) -> int:
    return sum(1 for record in ledger if record.get("type") == "task")


def verification_coverage(_state: dict[str, object], ledger: list[dict[str, object]]) -> float:
    verifications = [record for record in ledger if record.get("type") == "verification"]
    if not verifications:
        return 0.0
    complete = sum(
        1
        for record in verifications
        if all(record.get(field) for field in ("kind", "result", "recorded_at", "summary"))
    )
    return round(complete / len(verifications), 4)


def review_coverage(_state: dict[str, object], ledger: list[dict[str, object]]) -> float:
    return 1.0 if any(is_final_review_verification(record) for record in ledger) else 0.0


def prompt_log_pair_stub(_state: dict[str, object], ledger: list[dict[str, object]]) -> float:
    return 1.0 if core_prompt_log_pairs_complete(ledger) else 0.0


def coverage_metrics(state: dict[str, object], ledger: list[dict[str, object]]) -> dict[str, object]:
    return {
        "verification_coverage": verification_coverage(state, ledger),
        "review_coverage": review_coverage(state, ledger),
        "task_count": task_count(ledger),
        "prompt_log_pair_coverage": prompt_log_pair_stub(state, ledger),
        "prompt_log_pairs_complete": core_prompt_log_pairs_complete(ledger),
    }
