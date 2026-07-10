from __future__ import annotations

FINAL_REVIEW_KINDS = {"review", "manual_review", "git_diff"}


def is_final_review_verification(record: dict[str, object]) -> bool:
    return record.get("type") == "verification" and record.get("kind") in FINAL_REVIEW_KINDS


def prompt_log_pair_ratio(ledger: list[dict[str, object]]) -> float:
    dispatches = [
        record
        for record in ledger
        if record.get("type") in {"dispatch_started", "session_dispatch"}
    ]
    if not dispatches:
        return 1.0
    complete = sum(
        1
        for record in dispatches
        if isinstance(record.get("prompt_path"), str)
        and record.get("prompt_path")
        and isinstance(record.get("log_path"), str)
        and record.get("log_path")
    )
    return complete / len(dispatches)


def prompt_log_pairs_complete(ledger: list[dict[str, object]]) -> bool:
    return prompt_log_pair_ratio(ledger) == 1.0
