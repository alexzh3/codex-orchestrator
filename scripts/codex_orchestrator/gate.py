from __future__ import annotations

import fnmatch
from datetime import datetime, timezone
from pathlib import Path, PurePath

from .claims import (
    TERMINAL_TASK_STATUSES,
    file_claim_conflict_report,
    has_glob_meta,
    is_path_prefix,
    normalize_glob,
)
from .contract import LEGACY_CONSENSUS_STATUS_OUTCOMES
from .events import LEDGER_EVENT_SCHEMAS, validate_ledger_event
from .report import is_final_review_verification
from .store import report_path


UNRESOLVED_VERIFICATION_RESULTS = {"failed", "inconclusive", "needs_human_review"}
RESOLVING_CONSENSUS_OUTCOMES = {"consensus", "claude_decision"}
GENERIC_LEDGER_EVENT_TYPES = {"change", "event", "session_dispatch"}


def text_value(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def string_list_items(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str) and item]


def task_id_from_record(record: dict[str, object]) -> str | None:
    if record.get("type") == "task_checkpoint":
        return text_value(record.get("task_id"))
    return text_value(record.get("id"))


def task_states(records: list[dict[str, object]]) -> list[dict[str, object]]:
    tasks: dict[str, dict[str, object]] = {}
    order: list[str] = []

    def task_for(task_id: str) -> dict[str, object]:
        if task_id not in tasks:
            tasks[task_id] = {
                "id": task_id,
                "defined": False,
                "checkpoint_count": 0,
                "verification_required": [],
            }
            order.append(task_id)
        return tasks[task_id]

    for record in records:
        record_type = record.get("type")
        if record_type in {"task", "task_created"}:
            task_id = task_id_from_record(record)
            if not task_id:
                continue
            task = task_for(task_id)
            task["defined"] = True
            for field in ("title", "status", "owner"):
                value = text_value(record.get(field))
                if value:
                    task[field] = value
            if record_type == "task_created":
                requirements = record.get("verification_required")
                if isinstance(requirements, list):
                    task["verification_required"] = [
                        item for item in requirements if isinstance(item, str) and item
                    ]
        elif record_type == "task_updated":
            task_id = task_id_from_record(record)
            if not task_id:
                continue
            status = text_value(record.get("status"))
            if status:
                task_for(task_id)["status"] = status
        elif record_type == "task_checkpoint":
            task_id = task_id_from_record(record)
            if not task_id:
                continue
            task = task_for(task_id)
            task["checkpoint_count"] = int(task.get("checkpoint_count", 0)) + 1
            task["latest_checkpoint"] = record
            task.setdefault("owner", text_value(record.get("agent")))
            status = text_value(record.get("status"))
            if status:
                task["status"] = status
    return [tasks[task_id] for task_id in order]


def consensus_outcome_value(record: dict[str, object]) -> str | None:
    outcome = text_value(record.get("outcome"))
    if outcome:
        return outcome
    status = text_value(record.get("status"))
    return LEGACY_CONSENSUS_STATUS_OUTCOMES.get(status or "")


def consensus_requires_user(record: dict[str, object]) -> bool:
    return consensus_outcome_value(record) == "user_action_required" or record.get("requires_user") is True


def consensus_text(record: dict[str, object]) -> str:
    parts: list[str] = []
    for field in ("finding", "resolution", "root_cause", "summary"):
        value = text_value(record.get(field))
        if value:
            parts.append(value)
    evidence = record.get("evidence")
    if isinstance(evidence, list):
        parts.extend(item for item in evidence if isinstance(item, str))
    return "\n".join(parts).casefold()


def consensus_matches_verification(consensus: dict[str, object], verification: dict[str, object]) -> bool:
    haystack = consensus_text(consensus)
    if not haystack:
        return False

    def contains_reference(value: object) -> bool:
        text = text_value(value)
        if not text:
            return False
        needle = text.casefold().strip()
        if needle in haystack:
            return True
        trimmed = needle.rstrip(".:;!?")
        return len(trimmed) >= 4 and trimmed in haystack

    for field in ("command", "summary"):
        if contains_reference(verification.get(field)):
            return True
    for field in ("task_id", "check_id", "verification_id", "id"):
        if contains_reference(verification.get(field)):
            return True

    kind = text_value(verification.get("kind"))
    if kind:
        kind_text = kind.casefold()
        for phrase in (
            f"{kind_text} verification",
            f"{kind_text} check",
            f"{kind_text} failed",
            f"failed {kind_text}",
            f"{kind_text} failure",
        ):
            if phrase in haystack:
                return True
    return False


def has_later_overriding_consensus(
    records: list[dict[str, object]],
    start_index: int,
    verification: dict[str, object],
) -> bool:
    for record in records[start_index + 1 :]:
        if record.get("type") != "consensus":
            continue
        outcome = consensus_outcome_value(record)
        if (
            outcome in RESOLVING_CONSENSUS_OUTCOMES
            and record.get("requires_user") is not True
            and consensus_matches_verification(record, verification)
        ):
            return True
    return False


def unresolved_verification_records(records: list[dict[str, object]]) -> list[dict[str, object]]:
    unresolved: list[dict[str, object]] = []
    for index, record in enumerate(records):
        if record.get("type") != "verification":
            continue
        if record.get("result") not in UNRESOLVED_VERIFICATION_RESULTS:
            continue
        if has_later_overriding_consensus(records, index, record):
            continue
        unresolved.append(record)
    return unresolved


def verification_label(record: dict[str, object]) -> str:
    kind = text_value(record.get("kind")) or "verification"
    result = text_value(record.get("result")) or "unknown"
    summary = text_value(record.get("summary"))
    if summary:
        return f"{kind} verification ({result}): {summary}"
    return f"{kind} verification ({result})"


def verification_applies_to_task(record: dict[str, object], task_id: str) -> bool:
    record_task_id = text_value(record.get("task_id"))
    scope = text_value(record.get("scope"))
    covers_tasks = string_list_items(record.get("covers_tasks"))
    if not record_task_id and not scope and not covers_tasks:
        return True
    return record_task_id == task_id or task_id in covers_tasks or scope == "global"


def requirement_satisfied(records: list[dict[str, object]], task_id: str, requirement: str) -> bool:
    for record in records:
        if record.get("result") != "passed":
            continue
        record_type = record.get("type")
        if record_type == "verification":
            if not verification_applies_to_task(record, task_id):
                continue
            if requirement in {
                text_value(record.get("kind")),
                text_value(record.get("command")),
                text_value(record.get("summary")),
            }:
                return True
        elif record_type == "review":
            review_task_id = text_value(record.get("task_id"))
            if review_task_id and review_task_id != task_id:
                continue
            if requirement in {
                text_value(record.get("kind")),
                text_value(record.get("command")),
                text_value(record.get("summary")),
            }:
                return True
    return False


def has_passing_final_review(records: list[dict[str, object]]) -> bool:
    for record in records:
        if record.get("type") == "review" and record.get("result") == "passed":
            if is_run_wide_record(record) and (record.get("final") is True or record.get("kind") in {"diff", "manual"}):
                return True
        if is_run_wide_record(record) and is_final_review_verification(record) and record.get("result") == "passed":
            return True
    return False


def is_run_wide_record(record: dict[str, object]) -> bool:
    return not text_value(record.get("task_id")) and text_value(record.get("scope")) != "task"


def parse_recorded_at(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def latest_recorded_at(records: list[dict[str, object]]) -> datetime | None:
    timestamps = [
        parsed
        for record in records
        if record.get("type") != "gate_result"
        if (parsed := parse_recorded_at(record.get("recorded_at")))
    ]
    return max(timestamps) if timestamps else None


def report_freshness_issue(directory: Path, records: list[dict[str, object]]) -> str | None:
    latest = latest_recorded_at(records)
    if latest is None:
        return None
    path = report_path(directory)
    if not path.exists():
        return "missing-report: report.md does not exist"
    report_mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
    if report_mtime < latest:
        return "stale-report: report.md is older than the latest ledger event"
    return None


def low_confidence_warnings(state: dict[str, object]) -> list[str]:
    warnings: list[str] = []
    sessions = state.get("sessions")
    if not isinstance(sessions, list):
        return warnings
    for session in sessions:
        if not isinstance(session, dict) or session.get("parse_confidence") != "low":
            continue
        name = text_value(session.get("name")) or "<unnamed>"
        warnings.append(f"low-parser-confidence: session {name} has low parser confidence")
    return warnings


def file_claim_conflict_blocking_reasons(records: list[dict[str, object]]) -> list[str]:
    conflicts = file_claim_conflict_report(records).get("conflicts")
    if not isinstance(conflicts, list):
        return []

    reasons: list[str] = []
    for conflict in conflicts:
        if not isinstance(conflict, dict):
            continue
        task_a = text_value(conflict.get("task_a")) or "<unknown>"
        task_b = text_value(conflict.get("task_b")) or "<unknown>"
        claimed = "overlapping allowlists"
        overlap = conflict.get("overlap")
        if isinstance(overlap, list) and overlap and isinstance(overlap[0], dict):
            allow_a = text_value(overlap[0].get("allow_a"))
            allow_b = text_value(overlap[0].get("allow_b"))
            if allow_a and allow_b:
                claimed = allow_a if allow_a == allow_b else f"{allow_a} / {allow_b}"
        reasons.append(f"file-claim-conflict: {task_a} and {task_b} both claim {claimed}")
    return reasons


def task_change_allowlists(records: list[dict[str, object]]) -> dict[str, list[str]]:
    allowlists: dict[str, list[str]] = {}
    for record in records:
        if record.get("type") == "task_created":
            task_id = text_value(record.get("id"))
            allow = string_list_items(record.get("files_allowed"))
            declared = "files_allowed" in record
        elif record.get("type") == "file_claimed":
            task_id = text_value(record.get("task_id"))
            allow = string_list_items(record.get("allow"))
            declared = bool(allow)
        else:
            continue
        if task_id and declared:
            allowlists.setdefault(task_id, []).extend(allow)
    return allowlists


def path_matches_allowlist(path: str, allowlist: list[str]) -> bool:
    normalized_path = normalize_glob(path)
    for pattern in allowlist:
        normalized_pattern = normalize_glob(pattern)
        if not normalized_pattern:
            continue
        if not has_glob_meta(normalized_pattern) and is_path_prefix(normalized_pattern, normalized_path):
            return True
        if fnmatch.fnmatchcase(normalized_path, normalized_pattern):
            return True
        if PurePath(normalized_path).match(normalized_pattern):
            return True
    return False


def unclaimed_change_blocking_reasons(records: list[dict[str, object]]) -> list[str]:
    allowlists = task_change_allowlists(records)
    reasons: list[str] = []
    for record in records:
        if record.get("type") != "task_checkpoint":
            continue
        task_id = text_value(record.get("task_id"))
        if not task_id:
            continue
        if task_id not in allowlists:
            continue
        allowlist = allowlists[task_id]
        for path in string_list_items(record.get("files_changed")):
            if not path_matches_allowlist(path, allowlist):
                reasons.append(
                    f"unclaimed-change: task {task_id} changed {path} outside its files_allowed/file_claimed allowlist"
                )
    return reasons


def gate_blocking_reasons(directory: Path, records: list[dict[str, object]], diagnostics: list[dict[str, object]]) -> list[str]:
    blocking: list[str] = []
    for diagnostic in diagnostics:
        blocking.append(
            f"malformed-ledger: ledger.jsonl line {diagnostic.get('line_no')}: {diagnostic.get('error')}"
        )

    freshness_issue = report_freshness_issue(directory, records)
    if freshness_issue:
        blocking.append(freshness_issue)

    blocking.extend(file_claim_conflict_blocking_reasons(records))
    blocking.extend(unclaimed_change_blocking_reasons(records))

    tasks = task_states(records)
    for task in tasks:
        if not task.get("defined"):
            continue
        status = text_value(task.get("status")) or "unknown"
        if status not in TERMINAL_TASK_STATUSES:
            blocking.append(f"active-task: task {task['id']} status {status} is not terminal")

    for task in tasks:
        if not task.get("defined"):
            continue
        if task.get("status") == "complete" and int(task.get("checkpoint_count", 0)) == 0:
            blocking.append(f"missing-checkpoint: completed task {task['id']} has no task_checkpoint")

    for task in tasks:
        if task.get("status") != "complete":
            continue
        task_id = str(task["id"])
        for requirement in task.get("verification_required", []):
            if isinstance(requirement, str) and not requirement_satisfied(records, task_id, requirement):
                blocking.append(f"unmet-verification: task {task_id} requires {requirement}")

    for record in unresolved_verification_records(records):
        blocking.append(f"unresolved-verification: {verification_label(record)} has no overriding consensus")

    for record in records:
        if record.get("type") != "consensus" or not consensus_requires_user(record):
            continue
        finding = text_value(record.get("finding") or record.get("summary")) or "consensus record"
        blocking.append(f"unresolved-consensus: {finding} requires user action")

    if not has_passing_final_review(records):
        blocking.append("missing-final-review: no passing review or manual_review/git_diff verification recorded")
    return blocking


def task_has_verification(records: list[dict[str, object]], task_id: str) -> bool:
    for record in records:
        if record.get("type") == "verification" and verification_applies_to_task(record, task_id):
            return True
        if record.get("type") == "review" and text_value(record.get("task_id")) == task_id:
            return True
    return False


def accepted_run(state: dict[str, object], records: list[dict[str, object]]) -> bool:
    if state.get("status") == "accepted":
        return True
    for record in reversed(records):
        if record.get("type") == "run_closed":
            return record.get("status") == "accepted"
    return False


def schema_event_issues(records: list[dict[str, object]]) -> list[str]:
    issues: list[str] = []
    for index, record in enumerate(records, start=1):
        event_type = record.get("type")
        if not isinstance(event_type, str) or not event_type:
            issues.append(f"invalid-event: record {index} has no event type")
            continue
        if event_type in LEDGER_EVENT_SCHEMAS:
            try:
                validate_ledger_event(dict(record))
            except SystemExit as exc:
                issues.append(f"invalid-event: record {index} ({event_type}): {exc}")
        elif event_type not in GENERIC_LEDGER_EVENT_TYPES:
            issues.append(f"unknown-event: record {index} has unknown event type {event_type}")
    return issues


def dispatch_path_issues(records: list[dict[str, object]]) -> list[str]:
    issues: list[str] = []
    for record in records:
        if record.get("type") not in {"dispatch_started", "session_dispatch"}:
            continue
        missing = [field for field in ("prompt_path", "log_path") if not text_value(record.get(field))]
        if not missing:
            continue
        task_id = text_value(record.get("task_id")) or text_value(record.get("session")) or "<unknown>"
        issues.append(f"dispatch-missing-paths: dispatch {task_id} missing {', '.join(missing)}")
    return issues


def doctor_issues(directory: Path, state: dict[str, object], records: list[dict[str, object]], diagnostics: list[dict[str, object]]) -> list[str]:
    issues: list[str] = []
    for diagnostic in diagnostics:
        issues.append(
            f"malformed-ledger: ledger.jsonl line {diagnostic.get('line_no')}: {diagnostic.get('error')}"
        )
    issues.extend(schema_event_issues(records))
    issues.extend(dispatch_path_issues(records))

    tasks = task_states(records)
    for task in tasks:
        if task.get("defined") and int(task.get("checkpoint_count", 0)) == 0:
            issues.append(f"missing-checkpoint: task {task['id']} has no task_checkpoint")
    for task in tasks:
        if task.get("status") == "complete" and not task_has_verification(records, str(task["id"])):
            issues.append(f"missing-verification: completed task {task['id']} has no verification/review evidence")

    if accepted_run(state, records):
        for record in unresolved_verification_records(records):
            issues.append(f"accepted-run-unresolved-check: {verification_label(record)}")

    freshness_issue = report_freshness_issue(directory, records)
    if freshness_issue:
        issues.append(freshness_issue)
    return issues
