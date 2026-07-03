from __future__ import annotations

import hashlib


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
