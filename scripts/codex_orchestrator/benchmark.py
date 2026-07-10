from __future__ import annotations

import argparse

from .ledger import latest_record


def nullable_bool_type(value: str) -> bool | None:
    lowered = value.lower()
    if lowered in {"1", "true", "yes", "y", "pass", "passed"}:
        return True
    if lowered in {"0", "false", "no", "n", "fail", "failed"}:
        return False
    if lowered in {"null", "none", "unknown"}:
        return None
    raise argparse.ArgumentTypeError("value must be true, false, or null")


def string_or_none(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def latest_gate_passed(ledger: list[dict[str, object]]) -> bool | None:
    gate_result = latest_record(ledger, "gate_result")
    if not gate_result:
        return None
    ok = gate_result.get("ok")
    if isinstance(ok, bool):
        return ok
    passed = gate_result.get("passed")
    if isinstance(passed, bool):
        return passed
    result = gate_result.get("result") or gate_result.get("status")
    if isinstance(result, str):
        lowered = result.lower()
        if lowered in {"pass", "passed", "success", "succeeded"}:
            return True
        if lowered in {"fail", "failed", "failure"}:
            return False
    return None


def validate_benchmark_result(payload: dict[str, object]) -> None:
    required = (
        "suite",
        "case_id",
        "plugin_ref",
        "repo_commit",
        "passed",
        "wall_seconds",
        "claude_turns",
        "codex_sessions",
        "codex_reviews",
        "manual_interventions",
        "prompt_log_pairs_complete",
        "ledger_errors",
        "gate_passed",
        "external_score",
    )
    missing = [field for field in required if field not in payload]
    if missing:
        raise SystemExit(f"ERROR: benchmark result missing field(s): {', '.join(missing)}")
    for field in ("suite", "case_id", "plugin_ref", "repo_commit"):
        value = payload.get(field)
        if value is not None and not isinstance(value, str):
            raise SystemExit(f"ERROR: benchmark field {field} must be a string or null")
    for field in ("passed", "prompt_log_pairs_complete", "gate_passed"):
        value = payload.get(field)
        if field == "prompt_log_pairs_complete":
            if not isinstance(value, bool):
                raise SystemExit(f"ERROR: benchmark field {field} must be a boolean")
        elif value is not None and not isinstance(value, bool):
            raise SystemExit(f"ERROR: benchmark field {field} must be a boolean or null")
    for field in ("wall_seconds",):
        value = payload.get(field)
        if value is not None and (not isinstance(value, (int, float)) or value < 0):
            raise SystemExit(f"ERROR: benchmark field {field} must be a non-negative number or null")
    for field in ("claude_turns", "codex_sessions", "codex_reviews", "manual_interventions", "ledger_errors"):
        value = payload.get(field)
        if field in {"claude_turns", "manual_interventions"} and value is None:
            continue
        if type(value) is not int or value < 0:
            raise SystemExit(f"ERROR: benchmark field {field} must be a non-negative integer")
    external_score = payload.get("external_score")
    if external_score is not None and not isinstance(external_score, dict):
        raise SystemExit("ERROR: benchmark field external_score must be an object or null")
