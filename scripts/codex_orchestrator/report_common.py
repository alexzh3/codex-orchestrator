from __future__ import annotations

import json

from .contract import *

CONSENSUS_PLACEHOLDER = "No consensus decisions recorded."
REVIEW_PLACEHOLDER = "No review notes recorded."
SUMMARY_PLACEHOLDER = "No authored summary recorded."
CHANGES_PLACEHOLDER = "No authored changes recorded."
EVIDENCE_PLACEHOLDER = "No evidence recorded."
RISKS_PLACEHOLDER = "No unresolved risks or follow-ups recorded."
RUN_META_PLACEHOLDER = "No run metadata recorded."
TASK_GRAPH_PLACEHOLDER = "No task graph records recorded."
GATE_RESULT_PLACEHOLDER = "No gate result recorded."
REVIEW_KINDS = {"manual_review", "git_diff"}
FINAL_REVIEW_KINDS = {"review", "manual_review", "git_diff"}
SUMMARY_OPEN_ITEM_LIMIT = 140
TASK_RISK_STATUSES = {"blocked", "failed"}
UNRESOLVED_VERIFICATION_RESULTS = {"failed", "inconclusive", "needs_human_review"}
COMPLETENESS_COMPONENTS = (
    ("run_meta_present", "run_meta present", 0.15),
    ("tasks_listed", "all tasks listed", 0.15),
    ("changed_files_attributed", "all changed files attributed", 0.15),
    ("verification_records_complete", "verification records complete", 0.15),
    ("final_review_present", "final review present", 0.15),
    ("risks_reflect_failed_checks", "risks reflect failed/inconclusive checks", 0.10),
    ("gate_result_present", "gate result present", 0.10),
    ("prompt_log_pairs_complete", "prompt/log pairs complete", 0.05),
)
CONSENSUS_OUTCOME_LABELS = {
    "consensus": "consensus",
    "claude_decision": "Claude decision",
    "user_action_required": "user action required",
}
UNRESOLVED_CONSENSUS_OUTCOMES = {"user_action_required"}
VERIFICATION_KIND_LABELS = {
    "artifact_check": "Artifact check",
    "benchmark": "Benchmark",
    "build": "Build",
    "custom": "Custom check",
    "git_diff": "Git diff review",
    "lint": "Lint",
    "manual_review": "Manual / agent review",
    "screenshot": "Screenshot check",
    "test": "Test",
    "typecheck": "Typecheck",
}


def report_section(text: str, heading: str, default: str) -> str:
    marker = f"## {heading}"
    lines = text.splitlines()
    start_index: int | None = None
    for index, line in enumerate(lines):
        if line.strip() == marker:
            start_index = index + 1
            break
    if start_index is None:
        return default
    end_index = len(lines)
    for index in range(start_index, len(lines)):
        if lines[index].startswith("## "):
            end_index = index
            break
    section = "\n".join(lines[start_index:end_index]).strip()
    return section or default


def manual_consensus_section(text: str) -> str:
    section = report_section(text, "Consensus", "")
    for generated_marker in ("### Reviews", "### Decisions", "### Ledger Records"):
        if generated_marker in section:
            section = section.split(generated_marker, 1)[0].strip()
    return "\n".join(
        line for line in section.splitlines() if line.strip() != CONSENSUS_PLACEHOLDER
    ).strip()


def is_old_generated_summary(section: str) -> bool:
    lines = [line.strip() for line in section.splitlines() if line.strip()]
    return bool(lines) and lines[0].startswith("Run ID:") and any(
        line.startswith("- Acceptance:") for line in lines
    )


def authored_summary_section(text: str) -> str:
    section = report_section(text, "Summary", "")
    if "### Generated Digest" in section:
        section = section.split("### Generated Digest", 1)[0].strip()
    if is_old_generated_summary(section):
        return ""
    return "\n".join(
        line for line in section.splitlines() if line.strip() != SUMMARY_PLACEHOLDER
    ).strip()


def is_old_generated_changes(section: str) -> bool:
    lines = [line.strip() for line in section.splitlines() if line.strip()]
    if not lines:
        return False
    if lines == ["No changes recorded."]:
        return True
    return lines[0].startswith("- **") and all(
        line.startswith("- **") or line.startswith("- Owner:") or line.startswith("- Notes:")
        for line in lines
    )


def authored_changes_section(text: str) -> str:
    section = report_section(text, "Changes", "")
    if "### Ledger Records" in section:
        section = section.split("### Ledger Records", 1)[0].strip()
    if is_old_generated_changes(section):
        return ""
    return "\n".join(
        line
        for line in section.splitlines()
        if line.strip() not in {CHANGES_PLACEHOLDER, "No changes recorded."}
    ).strip()


def manual_review_section(text: str) -> str:
    section = report_section(text, "Review", "")
    generated_marker = "### Recorded Reviews"
    if generated_marker in section:
        section = section.split(generated_marker, 1)[0].strip()
    return "\n".join(
        line for line in section.splitlines() if line.strip() != REVIEW_PLACEHOLDER
    ).strip()


def text_field(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        return json.dumps(value, sort_keys=True)
    return str(value)


def inline_code(value: object) -> str:
    text = str(value).replace("`", "\\`")
    return f"`{text}`"


def clamp_unit(value: float) -> float:
    return max(0.0, min(1.0, value))


def string_list(value: object) -> list[str]:
    if isinstance(value, str) and value:
        return [value]
    if isinstance(value, list):
        return [item for item in value if isinstance(item, str) and item]
    return []


def latest_record(ledger: list[dict[str, object]], record_type: str) -> dict[str, object] | None:
    records = [record for record in ledger if record.get("type") == record_type]
    return records[-1] if records else None


def gate_result_ok(record: dict[str, object]) -> bool | None:
    ok = record.get("ok")
    if isinstance(ok, bool):
        return ok
    passed = record.get("passed")
    if isinstance(passed, bool):
        return passed
    result = record.get("result") or record.get("status")
    if isinstance(result, str):
        lowered = result.lower()
        if lowered in {"pass", "passed", "success", "succeeded"}:
            return True
        if lowered in {"fail", "failed", "failure"}:
            return False
    return None


def is_final_review_verification(record: dict[str, object]) -> bool:
    return record.get("type") == "verification" and record.get("kind") in FINAL_REVIEW_KINDS


def is_passed_typed_review(record: dict[str, object]) -> bool:
    return record.get("type") == "review" and record.get("result") == "passed"


def is_final_review_record(record: dict[str, object]) -> bool:
    return is_final_review_verification(record) or is_passed_typed_review(record)


def is_dispatch_record(record: dict[str, object]) -> bool:
    return record.get("type") in {"dispatch_started", "session_dispatch"}


def task_completion_ratio(task_records: list[dict[str, object]]) -> float:
    if not task_records:
        return 0.0
    complete = 0
    for record in task_records:
        if all(text_field(record.get(field)) for field in ("id", "title", "status")):
            complete += 1
    return complete / len(task_records)


def changed_file_attribution_ratio(
    ledger: list[dict[str, object]],
    task_records: list[dict[str, object]],
) -> float:
    task_ids = {text_field(record.get("id")) for record in task_records if text_field(record.get("id"))}
    total_files = 0
    attributed_files = 0
    for record in ledger:
        if record.get("type") != "task_checkpoint":
            continue
        files = string_list(record.get("files_changed"))
        if not files:
            continue
        total_files += len(files)
        task_ref = text_field(record.get("task_id"))
        if not task_ref or (task_ids and task_ref not in task_ids):
            continue
        attributed_files += len(files)
    if total_files == 0:
        return 1.0
    return attributed_files / total_files


def verification_completion_ratio(verification_records: list[dict[str, object]]) -> float:
    if not verification_records:
        return 0.0
    complete = 0
    for record in verification_records:
        if all(text_field(record.get(field)) for field in ("kind", "result", "recorded_at", "summary")):
            complete += 1
    return complete / len(verification_records)


def risks_reflect_failed_checks_ratio(verification_records: list[dict[str, object]]) -> float:
    if not verification_records:
        return 0.0
    unresolved = [
        record
        for record in verification_records
        if text_field(record.get("result")) in UNRESOLVED_VERIFICATION_RESULTS
    ]
    if not unresolved:
        return 1.0
    reflected = unresolved_items([], unresolved, [], [])
    return len(reflected) / len(unresolved)


def prompt_log_pair_ratio(ledger: list[dict[str, object]]) -> float:
    dispatches = [record for record in ledger if is_dispatch_record(record)]
    if not dispatches:
        return 1.0
    complete = 0
    for record in dispatches:
        if text_field(record.get("prompt_path")) and text_field(record.get("log_path")):
            complete += 1
    return complete / len(dispatches)


def prompt_log_pairs_complete(ledger: list[dict[str, object]]) -> bool:
    return prompt_log_pair_ratio(ledger) == 1.0


def gate_result_present(ledger: list[dict[str, object]]) -> bool:
    return any(record.get("type") == "gate_result" for record in ledger)


def task_records_for_score(ledger: list[dict[str, object]]) -> list[dict[str, object]]:
    task_created_records = [record for record in ledger if record.get("type") == "task_created"]
    if task_created_records:
        return task_created_records
    return [record for record in ledger if record.get("type") == "task"]


def has_work_evidence(ledger: list[dict[str, object]]) -> bool:
    evidence_types = {
        "consensus",
        "dispatch_started",
        "file_claimed",
        "gate_result",
        "review",
        "session_dispatch",
        "task",
        "task_checkpoint",
        "task_created",
        "task_updated",
        "verification",
    }
    return any(record.get("type") in evidence_types for record in ledger)


def report_completeness_score(state: dict[str, object], ledger: list[dict[str, object]]) -> dict[str, object]:
    del state
    run_meta = latest_record(ledger, "run_meta")
    task_records = task_records_for_score(ledger)
    verification_records = [record for record in ledger if record.get("type") == "verification"]
    has_evidence = has_work_evidence(ledger)
    ratios = {
        "run_meta_present": 1.0 if run_meta else 0.0,
        "tasks_listed": task_completion_ratio(task_records),
        "changed_files_attributed": changed_file_attribution_ratio(ledger, task_records) if has_evidence else 0.0,
        "verification_records_complete": verification_completion_ratio(verification_records),
        "final_review_present": 1.0 if any(is_final_review_record(record) for record in ledger) else 0.0,
        "risks_reflect_failed_checks": risks_reflect_failed_checks_ratio(verification_records),
        "gate_result_present": 1.0 if gate_result_present(ledger) else 0.0,
        "prompt_log_pairs_complete": prompt_log_pair_ratio(ledger) if has_evidence else 0.0,
    }
    components: dict[str, dict[str, object]] = {}
    for key, label, weight in COMPLETENESS_COMPONENTS:
        score = clamp_unit(float(ratios.get(key, 0.0)))
        earned = round(weight * score, 4)
        components[key] = {
            "label": label,
            "weight": weight,
            "score": round(score, 4),
            "earned": earned,
        }
    total = round(sum(float(component["earned"]) for component in components.values()), 4)
    return {"total": total, "components": components}


def score_total(score: dict[str, object]) -> float:
    total = score.get("total")
    return float(total) if isinstance(total, (int, float)) else 0.0


def score_component_lines(score: dict[str, object]) -> list[str]:
    components = score.get("components")
    if not isinstance(components, dict):
        return []
    lines: list[str] = []
    for key, _, _ in COMPLETENESS_COMPONENTS:
        component = components.get(key)
        if not isinstance(component, dict):
            continue
        label = text_field(component.get("label")) or key
        earned = float(component.get("earned") or 0.0)
        weight = float(component.get("weight") or 0.0)
        lines.append(f"  - {label}: {earned:.2f}/{weight:.2f}")
    return lines
