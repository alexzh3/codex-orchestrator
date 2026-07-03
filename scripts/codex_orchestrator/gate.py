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
from .resolution import (
    USER_OVERRIDE_CLEARS_ACCEPTANCE,
    attempt_count,
    clears_refs,
    computed_command_hash,
    consensus_clears_verification,
    consensus_resolution_basis,
    is_acceptance,
    is_executable,
    linked_verification_ids,
    min_repro_attempts_for,
    parse_recorded_at,
    parse_ref,
    rerun_link_issues,
    verifications_by_id,
)
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


def consensus_addresses_verification(
    consensus: dict[str, object],
    verification: dict[str, object],
    by_id: dict[str, list[dict[str, object]]],
) -> bool:
    refs = clears_refs(consensus)
    if refs:
        verification_id = verification.get("id")
        if not isinstance(verification_id, str) or not verification_id:
            return False
        if f"verification:{verification_id}" not in refs:
            return False
        return len(by_id.get(verification_id, [])) == 1
    return consensus_matches_verification(consensus, verification)


def has_later_overriding_consensus_with_ids(
    records: list[dict[str, object]],
    start_index: int,
    verification: dict[str, object],
    by_id: dict[str, list[dict[str, object]]],
    record_indices: dict[int, int] | None = None,
) -> bool:
    if record_indices is None:
        record_indices = {id(record): index for index, record in enumerate(records)}
    for consensus_index, record in enumerate(records[start_index + 1 :], start=start_index + 1):
        if record.get("type") != "consensus":
            continue
        outcome = consensus_outcome_value(record)
        if (
            outcome in RESOLVING_CONSENSUS_OUTCOMES
            and record.get("requires_user") is not True
            and consensus_addresses_verification(record, verification, by_id)
            and consensus_clears_verification(
                record,
                verification,
                by_id,
                consensus_index=consensus_index,
                record_indices=record_indices,
            )
        ):
            return True
    return False


def has_later_overriding_consensus(
    records: list[dict[str, object]],
    start_index: int,
    verification: dict[str, object],
) -> bool:
    return has_later_overriding_consensus_with_ids(records, start_index, verification, verifications_by_id(records))


def unresolved_verification_records(records: list[dict[str, object]]) -> list[dict[str, object]]:
    unresolved: list[dict[str, object]] = []
    by_id = verifications_by_id(records)
    record_indices = {id(record): index for index, record in enumerate(records)}
    for index, record in enumerate(records):
        if record.get("type") != "verification":
            continue
        if record.get("result") not in UNRESOLVED_VERIFICATION_RESULTS:
            continue
        if has_later_overriding_consensus_with_ids(records, index, record, by_id, record_indices):
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


def collect_blocking_findings(records: list[dict[str, object]]) -> list[dict[str, object]]:
    findings: list[dict[str, object]] = []
    for review_index, record in enumerate(records):
        if record.get("type") != "review":
            continue
        blocking_findings = record.get("blocking_findings")
        if not isinstance(blocking_findings, list):
            continue
        for item in blocking_findings:
            if not isinstance(item, dict):
                continue
            finding_id = text_value(item.get("id"))
            claim = text_value(item.get("claim"))
            if not finding_id or not claim:
                continue
            severity = text_value(item.get("severity")) or "P1"
            min_repro_attempts = item.get("min_repro_attempts")
            if type(min_repro_attempts) is not int or min_repro_attempts < 1:
                min_repro_attempts = 1
            findings.append(
                {
                    "id": finding_id,
                    "claim": claim,
                    "severity": severity,
                    "repro_command": text_value(item.get("repro_command")),
                    "min_repro_attempts": min_repro_attempts,
                    "review_index": review_index,
                    "task_id": text_value(record.get("task_id")) or "<unknown>",
                }
            )
    return findings


def finding_id_counts(records: list[dict[str, object]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for record in records:
        if record.get("type") != "review":
            continue
        blocking_findings = record.get("blocking_findings")
        if not isinstance(blocking_findings, list):
            continue
        for item in blocking_findings:
            if not isinstance(item, dict):
                continue
            finding_id = text_value(item.get("id"))
            if finding_id:
                counts[finding_id] = counts.get(finding_id, 0) + 1
    return counts


def finding_cleared_by_consensus(records: list[dict[str, object]], finding: dict[str, object]) -> bool:
    finding_id = text_value(finding.get("id"))
    review_index = finding.get("review_index")
    if not finding_id or type(review_index) is not int:
        return False
    ref = f"finding:{finding_id}"
    for record in records[review_index + 1 :]:
        if record.get("type") != "consensus":
            continue
        if consensus_outcome_value(record) not in RESOLVING_CONSENSUS_OUTCOMES:
            continue
        if record.get("requires_user") is True:
            continue
        if consensus_resolution_basis(record) not in {"accepted_risk", "user_override"}:
            continue
        if ref in clears_refs(record):
            return True
    return False


def repro_verifications_for_finding(
    records: list[dict[str, object]],
    finding: dict[str, object],
) -> list[dict[str, object]]:
    finding_id = text_value(finding.get("id"))
    repro_command = text_value(finding.get("repro_command"))
    review_index = finding.get("review_index")
    if not finding_id or not repro_command or type(review_index) is not int:
        return []
    repro_command_hash = computed_command_hash(repro_command)
    verifications: list[dict[str, object]] = []
    for index, record in enumerate(records):
        if index <= review_index:
            continue
        if record.get("type") != "verification" or record.get("finding_id") != finding_id:
            continue
        command = text_value(record.get("command"))
        if not command:
            continue
        if computed_command_hash(command) != repro_command_hash:
            continue
        verifications.append(record)
    return verifications


def pending_repro_blocking_reasons(records: list[dict[str, object]]) -> list[str]:
    reasons: list[str] = []
    seen_reasons: set[str] = set()
    unresolved_repro_ids = {id(record) for record in unresolved_verification_records(records)}

    def append_reason(reason: str) -> None:
        if reason in seen_reasons:
            return
        seen_reasons.add(reason)
        reasons.append(reason)

    for finding in collect_blocking_findings(records):
        severity = text_value(finding.get("severity")) or "P1"
        if severity not in {"P0", "P1"}:
            continue
        if finding_cleared_by_consensus(records, finding):
            continue
        if not finding.get("repro_command"):
            continue
        finding_id = str(finding["id"])
        claim = str(finding["claim"])
        repro_records = repro_verifications_for_finding(records, finding)
        if not repro_records:
            append_reason(
                f"pending-repro: finding {finding_id} ({severity}) '{claim}' has no passing repro verification"
            )
            continue
        if any(id(record) in unresolved_repro_ids for record in repro_records):
            continue
        passing_attempts = sum(attempt_count(record) for record in repro_records if record.get("result") == "passed")
        min_repro_attempts = int(finding.get("min_repro_attempts", 1))
        if passing_attempts < min_repro_attempts:
            append_reason(
                f"pending-repro: finding {finding_id} ({severity}) '{claim}' "
                f"has {passing_attempts} passing repro attempt(s), needs {min_repro_attempts}"
            )
    return reasons


def gate_warning_reasons(records: list[dict[str, object]]) -> list[str]:
    warnings: list[str] = []
    for finding in collect_blocking_findings(records):
        severity = text_value(finding.get("severity")) or "P1"
        if severity not in {"P0", "P1"}:
            continue
        if finding_cleared_by_consensus(records, finding):
            continue
        if finding.get("repro_command"):
            continue
        finding_id = str(finding["id"])
        claim = str(finding["claim"])
        warnings.append(
            f"finding-no-repro-command: finding {finding_id} ({severity}) "
            f"'{claim}' has no repro_command and cannot block"
        )
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
        blocking.append(
            f"unresolved-verification: {verification_label(record)} "
            "has no overriding consensus with a valid evidence basis"
        )

    blocking.extend(pending_repro_blocking_reasons(records))

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


def consensus_finding_label(record: dict[str, object]) -> str:
    return text_value(record.get("finding")) or text_value(record.get("summary")) or "consensus record"


def all_finding_ids(records: list[dict[str, object]]) -> set[str]:
    return set(finding_id_counts(records))


def consensus_ref_issues(records: list[dict[str, object]]) -> list[str]:
    issues: list[str] = []
    by_id = verifications_by_id(records)
    finding_ids = all_finding_ids(records)
    for record in records:
        if record.get("type") != "consensus":
            continue
        finding = consensus_finding_label(record)
        for field in ("clears", "evidence_refs"):
            refs = record.get(field)
            if not isinstance(refs, list):
                continue
            for ref in refs:
                parsed = parse_ref(ref)
                if parsed is None:
                    issues.append(
                        f"malformed-ref: consensus '{finding}' {field} entry '{ref}' "
                        "is not verification:<id> or finding:<id>"
                    )
                    continue
                ref_type, ref_id = parsed
                if ref_type == "verification" and ref_id not in by_id:
                    issues.append(f"dangling-ref: consensus '{finding}' references unknown verification id '{ref_id}'")
                elif ref_type == "finding" and ref_id not in finding_ids:
                    issues.append(f"dangling-ref: consensus '{finding}' references unknown finding id '{ref_id}'")
    return issues


def cleared_verification_ids(record: dict[str, object]) -> list[str]:
    ids: list[str] = []
    seen: set[str] = set()
    for ref in clears_refs(record):
        parsed = parse_ref(ref)
        if parsed is None:
            continue
        ref_type, ref_id = parsed
        if ref_type != "verification" or ref_id in seen:
            continue
        ids.append(ref_id)
        seen.add(ref_id)
    return ids


def rerun_link_doctor_issues(records: list[dict[str, object]]) -> list[str]:
    issues: list[str] = []
    by_id = verifications_by_id(records)
    record_indices = {id(record): index for index, record in enumerate(records)}
    for consensus_index, record in enumerate(records):
        if record.get("type") != "consensus":
            continue
        basis = consensus_resolution_basis(record)
        if basis not in {"rerun_passed", "repro_not_reproduced"}:
            continue
        finding = consensus_finding_label(record)
        linked_ids = linked_verification_ids(record)
        for verification_id in cleared_verification_ids(record):
            verification_records = by_id.get(verification_id, [])
            if len(verification_records) != 1:
                continue
            verification = verification_records[0]
            min_attempts = min_repro_attempts_for(verification) if basis == "repro_not_reproduced" else 1
            if not linked_ids:
                issues.append(
                    f"invalid-rerun-link: consensus '{finding}' clears verification '{verification_id}' "
                    f"with basis {basis} but links no passing rerun"
                )
                continue
            attempted: list[tuple[str, list[str]]] = []
            has_valid_link = False
            for linked_id in linked_ids:
                linked_records = by_id.get(linked_id, [])
                if len(linked_records) != 1:
                    continue
                linked_record = linked_records[0]
                reasons = rerun_link_issues(
                    linked_record,
                    verification,
                    min_attempts=min_attempts,
                    link_index=record_indices.get(id(linked_record)),
                    consensus_index=consensus_index,
                )
                if reasons:
                    attempted.append((linked_id, reasons))
                else:
                    has_valid_link = True
            if has_valid_link:
                continue
            for linked_id, reasons in attempted:
                issues.append(
                    f"invalid-rerun-link: consensus '{finding}' link '{linked_id}' "
                    f"does not supersede verification '{verification_id}' ({', '.join(reasons)})"
                )
    return issues


def ineffective_clear_issues(records: list[dict[str, object]]) -> list[str]:
    issues: list[str] = []
    by_id = verifications_by_id(records)
    for record in records:
        if record.get("type") != "consensus" or not clears_refs(record):
            continue
        basis = consensus_resolution_basis(record)
        if basis not in {"accepted_risk", "non_executable_convention", "user_override"}:
            continue
        finding = consensus_finding_label(record)
        for verification_id in cleared_verification_ids(record):
            verification_records = by_id.get(verification_id, [])
            if len(verification_records) != 1:
                continue
            verification = verification_records[0]
            if basis in {"accepted_risk", "non_executable_convention"}:
                if is_executable(verification):
                    issues.append(
                        f"ineffective-clear: consensus '{finding}' (basis {basis}) "
                        f"cannot clear verification '{verification_id}' (executable command)"
                    )
                if is_acceptance(verification):
                    issues.append(
                        f"ineffective-clear: consensus '{finding}' (basis {basis}) "
                        f"cannot clear verification '{verification_id}' (acceptance test)"
                    )
            elif basis == "user_override" and not USER_OVERRIDE_CLEARS_ACCEPTANCE and is_acceptance(verification):
                issues.append(
                    f"ineffective-clear: consensus '{finding}' (basis {basis}) "
                    f"cannot clear verification '{verification_id}' (acceptance test)"
                )
    return issues


def duplicate_evidence_id_issues(records: list[dict[str, object]]) -> list[str]:
    issues: list[str] = []
    for verification_id, verification_records in verifications_by_id(records).items():
        if len(verification_records) > 1:
            issues.append(f"duplicate-verification-id: verification id '{verification_id}' recorded {len(verification_records)} times")
    for finding_id, count in finding_id_counts(records).items():
        if count > 1:
            issues.append(f"duplicate-finding-id: blocking finding id '{finding_id}' recorded {count} times")
    return issues


def command_hash_issues(records: list[dict[str, object]]) -> list[str]:
    issues: list[str] = []
    for record in records:
        if record.get("type") != "verification":
            continue
        command = record.get("command")
        stored_hash = record.get("command_hash")
        if not isinstance(command, str) or not isinstance(stored_hash, str):
            continue
        if stored_hash == computed_command_hash(command):
            continue
        verification_id = text_value(record.get("id")) or "<unknown>"
        issues.append(f"command-hash-mismatch: verification '{verification_id}' stored command_hash does not match its command")
    return issues


def finding_repro_issues(records: list[dict[str, object]]) -> list[str]:
    issues: list[str] = []
    for finding in collect_blocking_findings(records):
        if finding.get("repro_command"):
            continue
        issues.append(
            f"finding-missing-repro: blocking finding '{finding['id']}' "
            f"in review for task {finding['task_id']} has no repro_command"
        )
    return issues


def doctor_issues(directory: Path, state: dict[str, object], records: list[dict[str, object]], diagnostics: list[dict[str, object]]) -> list[str]:
    issues: list[str] = []
    for diagnostic in diagnostics:
        issues.append(
            f"malformed-ledger: ledger.jsonl line {diagnostic.get('line_no')}: {diagnostic.get('error')}"
        )
    issues.extend(schema_event_issues(records))
    issues.extend(dispatch_path_issues(records))
    issues.extend(consensus_ref_issues(records))
    issues.extend(rerun_link_doctor_issues(records))
    issues.extend(ineffective_clear_issues(records))
    issues.extend(duplicate_evidence_id_issues(records))
    issues.extend(command_hash_issues(records))
    issues.extend(finding_repro_issues(records))

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
