from __future__ import annotations

import hashlib
from datetime import datetime, timezone

from .contract import DEFAULT_RESOLUTION_BASIS


VERIFICATION_REF_PREFIX = "verification:"
FINDING_REF_PREFIX = "finding:"
USER_OVERRIDE_CLEARS_ACCEPTANCE = False
MIN_STOCHASTIC_REPRO_ATTEMPTS = 3


def normalize_command(command: str) -> str:
    return command.replace("\r\n", "\n").strip()


def computed_command_hash(command: str) -> str:
    digest = hashlib.sha256(normalize_command(command).encode("utf-8")).hexdigest()
    return f"sha256:{digest}"


def parse_ref(ref: object) -> tuple[str, str] | None:
    if not isinstance(ref, str):
        return None
    if ref.startswith(VERIFICATION_REF_PREFIX):
        ref_id = ref[len(VERIFICATION_REF_PREFIX) :]
        return ("verification", ref_id) if ref_id else None
    if ref.startswith(FINDING_REF_PREFIX):
        ref_id = ref[len(FINDING_REF_PREFIX) :]
        return ("finding", ref_id) if ref_id else None
    return None


def clears_refs(record: dict) -> list[str]:
    value = record.get("clears") or []
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str)]


def evidence_refs(record: dict) -> list[str]:
    value = record.get("evidence_refs") or []
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str)]


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


def verifications_by_id(records: list[dict[str, object]]) -> dict[str, list[dict[str, object]]]:
    by_id: dict[str, list[dict[str, object]]] = {}
    for record in records:
        if record.get("type") != "verification":
            continue
        verification_id = record.get("id")
        if isinstance(verification_id, str) and verification_id:
            by_id.setdefault(verification_id, []).append(record)
    return by_id


def is_executable(v: dict) -> bool:
    command = v.get("command")
    return isinstance(command, str) and bool(command)


def is_acceptance(v: dict) -> bool:
    return v.get("acceptance_test") is True


def consensus_resolution_basis(c: dict) -> str:
    basis = c.get("resolution_basis")
    return basis if isinstance(basis, str) and basis else DEFAULT_RESOLUTION_BASIS


def attempt_count(v: dict) -> int:
    value = v.get("attempt_count")
    if type(value) is int and value >= 1:
        return value
    return 1


def min_repro_attempts_for(v: dict) -> int:
    return MIN_STOCHASTIC_REPRO_ATTEMPTS if v.get("stochastic") is True else 1


def user_override_clears(v: dict) -> bool:
    return USER_OVERRIDE_CLEARS_ACCEPTANCE or not is_acceptance(v)


def linked_verification_ids(c: dict) -> list[str]:
    ids: list[str] = []
    seen: set[str] = set()
    for ref in clears_refs(c) + evidence_refs(c):
        parsed = parse_ref(ref)
        if parsed is None:
            continue
        ref_type, ref_id = parsed
        if ref_type != "verification" or ref_id in seen:
            continue
        ids.append(ref_id)
        seen.add(ref_id)
    return ids


def rerun_link_issues(link: dict, v: dict, min_attempts: int = 1) -> list[str]:
    issues: list[str] = []
    result = link.get("result")
    if result != "passed":
        issues.append(f"result {result}")

    link_recorded_at = parse_recorded_at(link.get("recorded_at"))
    verification_recorded_at = parse_recorded_at(v.get("recorded_at"))
    if link_recorded_at is None or verification_recorded_at is None or link_recorded_at <= verification_recorded_at:
        issues.append("not newer")

    if (link.get("task_id") or "") != (v.get("task_id") or ""):
        issues.append("task mismatch")
    if link.get("kind") != v.get("kind"):
        issues.append("kind mismatch")

    link_command = link.get("command")
    verification_command = v.get("command")
    if not isinstance(link_command, str) or not link_command:
        issues.append("command hash mismatch")
    elif not isinstance(verification_command, str) or not verification_command:
        issues.append("command hash mismatch")
    elif computed_command_hash(link_command) != computed_command_hash(verification_command):
        issues.append("command hash mismatch")

    if (link.get("acceptance_test") is True) != (v.get("acceptance_test") is True):
        issues.append("acceptance flag mismatch")

    attempts = attempt_count(link)
    if attempts < min_attempts:
        issues.append(f"attempts {attempts} < {min_attempts}")
    return issues


def consensus_clears_verification(c: dict, v: dict, by_id: dict[str, list[dict[str, object]]]) -> bool:
    basis = consensus_resolution_basis(c)
    if basis == "user_override":
        return user_override_clears(v)
    if basis in {"accepted_risk", "non_executable_convention"}:
        return not is_executable(v) and not is_acceptance(v)
    if basis in {"rerun_passed", "repro_not_reproduced"}:
        min_attempts = min_repro_attempts_for(v) if basis == "repro_not_reproduced" else 1
        for verification_id in linked_verification_ids(c):
            records = by_id.get(verification_id, [])
            if len(records) != 1:
                continue
            if not rerun_link_issues(records[0], v, min_attempts=min_attempts):
                return True
        return False
    return False
