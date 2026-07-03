from __future__ import annotations

import argparse
import difflib
import json
import sys
import time
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
SCRIPTS_DIR = ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from codex_orch import (  # noqa: E402
    collect_warnings,
    read_jsonl_with_warnings,
    validate_benchmark_result,
)
from codex_orchestrator.report import (  # noqa: E402
    is_final_review_verification,
    latest_record,
    prompt_log_pairs_complete,
    render_report,
)
from codex_orchestrator.scoring import coverage_metrics, report_score  # noqa: E402


DEFAULT_CASE_DIR = ROOT / "bench" / "cases" / "replay" / "long-run-001"


@dataclass(frozen=True)
class ReplayResult:
    case_dir: Path
    payload: dict[str, object]
    golden_match: bool
    generated_report: str
    expected_report: str
    warnings: list[str]
    ledger_diagnostics: list[dict[str, object]]
    updated_golden: bool


def load_json_object(path: Path) -> dict[str, object]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return payload


def normalize_report(text: str) -> str:
    normalized = text.replace("\r\n", "\n")
    return normalized if normalized.endswith("\n") else normalized + "\n"


def case_path(case_dir: Path, field: str, case: dict[str, object]) -> Path:
    value = case.get(field)
    if not isinstance(value, str) or not value:
        raise ValueError(f"case {case_dir} is missing string field {field}")
    return case_dir / value


def string_or_none(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def latest_gate_passed(ledger: list[dict[str, object]]) -> bool | None:
    gate_result = latest_record(ledger, "gate_result")
    if not gate_result:
        return None
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


def manual_intervention_count(ledger: list[dict[str, object]]) -> int:
    total = 0
    for record in ledger:
        if record.get("type") != "consensus":
            continue
        if record.get("requires_user") is True or record.get("outcome") == "user_action_required":
            total += 1
    return total


def render_case_report(
    case: dict[str, object],
    state: dict[str, object],
    ledger: list[dict[str, object]],
    warnings: list[str],
) -> str:
    generated_at = case.get("generated_at")
    if not isinstance(generated_at, str) or not generated_at:
        raise ValueError("case generated_at must be a fixed ISO timestamp")
    return render_report(
        state=state,
        ledger=ledger,
        existing_report="",
        warnings=warnings,
        generated_at=generated_at,
    )


def build_payload(
    *,
    case: dict[str, object],
    state: dict[str, object],
    ledger: list[dict[str, object]],
    ledger_diagnostics: list[dict[str, object]],
    golden_match: bool,
    wall_seconds: float,
) -> dict[str, object]:
    run_meta = latest_record(ledger, "run_meta") or {}
    sessions = state.get("sessions") if isinstance(state.get("sessions"), list) else []
    metrics = coverage_metrics(state, ledger)
    payload: dict[str, object] = {
        "suite": string_or_none(case.get("suite")) or string_or_none(run_meta.get("benchmark_suite")),
        "case_id": string_or_none(case.get("id")) or string_or_none(run_meta.get("benchmark_case_id")),
        "plugin_ref": string_or_none(case.get("plugin_ref")) or string_or_none(run_meta.get("plugin_git_sha")),
        "repo_commit": string_or_none(run_meta.get("repo_commit")),
        "passed": golden_match and len(ledger_diagnostics) == 0,
        "wall_seconds": round(wall_seconds, 6),
        "claude_turns": 0,
        "codex_sessions": len(sessions),
        "codex_reviews": sum(1 for record in ledger if is_final_review_verification(record)),
        "manual_interventions": manual_intervention_count(ledger),
        "prompt_log_pairs_complete": prompt_log_pairs_complete(ledger),
        "ledger_errors": len(ledger_diagnostics),
        "gate_passed": latest_gate_passed(ledger),
        "report_score": report_score(state, ledger),
        "external_score": {
            "golden_match": golden_match,
            **metrics,
        },
    }
    validate_benchmark_result(payload)
    return payload


def diff_reports(expected: str, generated: str) -> str:
    return "".join(
        difflib.unified_diff(
            expected.splitlines(keepends=True),
            generated.splitlines(keepends=True),
            fromfile="expected-report.md",
            tofile="generated-report.md",
        )
    )


def run_case(case_dir: Path, *, update_golden: bool = False) -> ReplayResult:
    case_dir = case_dir.resolve()
    case = load_json_object(case_dir / "case.json")
    state = load_json_object(case_path(case_dir, "state", case))
    ledger, ledger_diagnostics = read_jsonl_with_warnings(case_path(case_dir, "ledger", case))
    warnings = collect_warnings(state, ledger_diagnostics)

    started = time.perf_counter()
    generated_report = render_case_report(case, state, ledger, warnings)
    wall_seconds = time.perf_counter() - started

    expected_path = case_path(case_dir, "expected_report", case)
    expected_report = expected_path.read_text(encoding="utf-8") if expected_path.exists() else ""
    if update_golden:
        expected_path.write_text(generated_report, encoding="utf-8")
        expected_report = generated_report

    golden_match = normalize_report(generated_report) == normalize_report(expected_report)
    payload = build_payload(
        case=case,
        state=state,
        ledger=ledger,
        ledger_diagnostics=ledger_diagnostics,
        golden_match=golden_match,
        wall_seconds=wall_seconds,
    )
    return ReplayResult(
        case_dir=case_dir,
        payload=payload,
        golden_match=golden_match,
        generated_report=generated_report,
        expected_report=expected_report,
        warnings=warnings,
        ledger_diagnostics=ledger_diagnostics,
        updated_golden=update_golden,
    )


def case_dir_arg(value: str) -> Path:
    path = Path(value)
    return path.parent if path.name == "case.json" else path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run a deterministic replay benchmark case.")
    parser.add_argument("case", nargs="?", default=str(DEFAULT_CASE_DIR), type=case_dir_arg)
    parser.add_argument("--update-golden", action="store_true", help="Rewrite expected-report.md.")
    parser.add_argument("--out", help="Write the benchmark-result JSON to this path.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    result = run_case(args.case, update_golden=args.update_golden)
    output = json.dumps(result.payload, indent=2, sort_keys=True) + "\n"
    if args.out:
        Path(args.out).write_text(output, encoding="utf-8")
    sys.stdout.write(output)
    if not result.golden_match:
        sys.stderr.write(diff_reports(result.expected_report, result.generated_report))
        return 1
    if result.ledger_diagnostics:
        sys.stderr.write(f"ledger contains {len(result.ledger_diagnostics)} malformed line(s)\n")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
