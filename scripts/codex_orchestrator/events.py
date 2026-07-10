from __future__ import annotations

import re

from .contract import *
from .store import utc_now


COMMAND_HASH_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")
BLOCKING_FINDING_FIELDS = (
    "id",
    "claim",
    "severity",
    "file_refs",
    "repro_command",
    "min_repro_attempts",
)
BLOCKING_FINDING_REQUIRED_STRINGS = ("id", "claim")
BLOCKING_FINDING_STRING_FIELDS = ("id", "claim", "repro_command")


LEDGER_EVENT_SCHEMAS = {
    "verification": {
        "timestamp": True,
        "required": ("type", "kind", "result", "recorded_at", "summary"),
        "strings": (
            "type",
            "recorded_at",
            "summary",
            "command",
            "notes",
            "task_id",
            "id",
            "command_hash",
            "finding_id",
        ),
        "enums": {
            "kind": ALLOWED_VERIFICATION_KINDS,
            "result": ALLOWED_VERIFICATION_RESULTS,
            "scope": VERIFICATION_SCOPE_ORDER,
        },
        "ints": ("exit_code",),
        "positive_ints": ("attempt_count",),
        "bools": ("stochastic", "acceptance_test"),
        "string_arrays": ("artifacts", "covers_tasks"),
        "scalar_maps": ("thresholds",),
    },
    "consensus": {
        "timestamp": True,
        "required": ("type", "recorded_at", "finding", "outcome", "resolution", "evidence"),
        "strings": ("type", "recorded_at", "finding", "resolution", "root_cause", "summary"),
        "enums": {
            "outcome": CONSENSUS_OUTCOME_ORDER,
            "risk_level": tuple(sorted(ALLOWED_RISK_LEVELS)),
            "status": tuple(sorted(ALLOWED_LEGACY_CONSENSUS_STATUSES)),
            "resolution_basis": RESOLUTION_BASIS_ORDER,
        },
        "bools": ("requires_user",),
        "string_arrays": ("clears", "evidence_refs"),
        "non_empty_string_arrays": ("evidence",),
    },
    "task": {
        "required": ("type", "id", "title", "status"),
        "strings": ("type", "id", "title", "owner", "created_at", "updated_at", "notes"),
        "enums": {"status": TASK_STATUS_ORDER},
    },
    "task_created": {
        "timestamp": True,
        "required": ("type", "id", "title", "status"),
        "strings": ("type", "id", "title", "owner", "recorded_at", "goal"),
        "enums": {"status": TASK_STATUS_ORDER},
        "string_arrays": (
            "depends_on",
            "files_allowed",
            "files_forbidden",
            "acceptance",
            "verification_required",
            "context",
            "constraints",
        ),
    },
    "task_updated": {
        "timestamp": True,
        "required": ("type", "id", "status"),
        "strings": ("type", "id", "status", "notes", "recorded_at"),
        "enums": {"status": TASK_STATUS_ORDER},
    },
    "file_claimed": {
        "timestamp": True,
        "required": ("type", "task_id", "agent", "allow"),
        "strings": ("type", "task_id", "agent", "recorded_at"),
        "non_empty_string_arrays": ("allow",),
        "string_arrays": ("forbid",),
    },
    "dispatch_started": {
        "timestamp": True,
        "required": ("type", "task_id", "agent", "mode", "prompt_path", "log_path"),
        "strings": (
            "type",
            "task_id",
            "agent",
            "mode",
            "prompt_path",
            "log_path",
            "reuse_reason",
            "worktree",
            "recorded_at",
        ),
        "enums": {"mode": DISPATCH_MODE_ORDER},
        "bools": ("fresh_session",),
    },
    "dispatch_completed": {
        "timestamp": True,
        "required": ("type", "task_id", "agent", "status"),
        "strings": ("type", "task_id", "agent", "status", "recorded_at"),
        "enums": {"status": SESSION_STATUS_ORDER},
    },
    "task_checkpoint": {
        "timestamp": True,
        "required": ("type", "task_id", "agent", "status", "summary", "files_changed"),
        "strings": ("type", "task_id", "agent", "status", "summary", "recorded_at"),
        "enums": {"status": TASK_STATUS_ORDER},
        "string_arrays": ("files_changed", "unresolved_blockers"),
        "object_arrays": ("tests_run",),
    },
    "review": {
        "timestamp": True,
        "required": ("type", "task_id", "reviewer", "kind", "result"),
        "strings": (
            "type",
            "task_id",
            "reviewer",
            "kind",
            "result",
            "command",
            "prompt_path",
            "log_path",
            "summary",
            "recorded_at",
        ),
        "enums": {
            "kind": REVIEW_KIND_ORDER,
            "result": ALLOWED_VERIFICATION_RESULTS,
        },
        "bools": ("final",),
        "string_arrays": ("findings",),
        "finding_arrays": ("blocking_findings",),
    },
    "gate_result": {
        "timestamp": True,
        "required": ("type", "ok"),
        "strings": ("type", "recorded_at"),
        "bools": ("ok", "passed"),
        "string_arrays": ("blocking", "warnings"),
    },
    "run_closed": {
        "timestamp": True,
        "required": ("type", "status"),
        "strings": ("type", "status", "summary", "recorded_at"),
        "enums": {"status": STATE_STATUS_ORDER},
    },
    "run_meta": {
        "timestamp": True,
        "required": ("type", "recorded_at", "run_id", "protocol_version", "schema_version"),
        "strings": ("type", "recorded_at", "run_id", "protocol_version", "schema_version"),
        "nullable_strings": (
            "plugin_version",
            "plugin_git_sha",
            "claude_code_version",
            "codex_cli_version",
            "repo_commit",
            "benchmark_suite",
            "benchmark_case_id",
        ),
        "run_meta_configs": ("config",),
    },
}


def event_schema_fields(schema: dict[str, object]) -> set[str]:
    fields: set[str] = set(schema.get("required", ()))
    for key in (
        "strings",
        "nullable_strings",
        "ints",
        "positive_ints",
        "bools",
        "string_arrays",
        "non_empty_string_arrays",
        "object_arrays",
        "finding_arrays",
        "scalar_maps",
        "run_meta_configs",
    ):
        fields.update(schema.get(key, ()))
    fields.update(schema.get("enums", {}).keys())
    return fields


def validate_string_fields(event_type: str, event: dict[str, object], schema: dict[str, object]) -> None:
    required = set(schema.get("required", ()))
    for field in schema.get("strings", ()):
        if field not in event:
            continue
        value = event[field]
        if not isinstance(value, str) or (field in required and not value):
            suffix = "a non-empty string" if field in required else "a string"
            raise SystemExit(f"ERROR: {event_type} field {field} must be {suffix}")


def validate_enum_fields(event_type: str, event: dict[str, object], schema: dict[str, object]) -> None:
    for field, allowed_values in schema.get("enums", {}).items():
        if field not in event:
            continue
        value = event[field]
        if not isinstance(value, str) or value not in allowed_values:
            allowed = ", ".join(allowed_values)
            raise SystemExit(f"ERROR: {event_type} {field} must be one of: {allowed}")


def validate_typed_fields(event_type: str, event: dict[str, object], schema: dict[str, object]) -> None:
    required = set(schema.get("required", ()))
    for field in schema.get("nullable_strings", ()):
        value = event.get(field)
        if value is not None and not isinstance(value, str):
            raise SystemExit(f"ERROR: {event_type} field {field} must be a string or null")
    for field in schema.get("ints", ()):
        value = event.get(field)
        if value is None:
            if field in required:
                raise SystemExit(f"ERROR: {event_type} field {field} must be an integer")
            continue
        if value is not None and type(value) is not int:
            raise SystemExit(f"ERROR: {event_type} field {field} must be an integer or null")
    for field in schema.get("positive_ints", ()):
        value = event.get(field)
        if value is None:
            if field in required:
                raise SystemExit(f"ERROR: {event_type} field {field} must be an integer >= 1")
            continue
        if type(value) is not int or value < 1:
            raise SystemExit(f"ERROR: {event_type} field {field} must be an integer >= 1")
    for field in schema.get("bools", ()):
        value = event.get(field)
        if value is None:
            if field in required:
                raise SystemExit(f"ERROR: {event_type} field {field} must be a boolean")
            continue
        if value is not None and not isinstance(value, bool):
            raise SystemExit(f"ERROR: {event_type} field {field} must be a boolean")
    for field in schema.get("string_arrays", ()):
        value = event.get(field)
        if value is None:
            if field in required:
                raise SystemExit(f"ERROR: {event_type} field {field} must be a string array")
            continue
        if value is not None and (
            not isinstance(value, list) or not all(isinstance(item, str) for item in value)
        ):
            raise SystemExit(f"ERROR: {event_type} field {field} must be a string array")
    for field in schema.get("non_empty_string_arrays", ()):
        value = event.get(field)
        if value is None:
            if field in required:
                raise SystemExit(f"ERROR: {event_type} field {field} must be a non-empty string array")
            continue
        if not isinstance(value, list) or not value or not all(isinstance(item, str) and item for item in value):
            raise SystemExit(f"ERROR: {event_type} field {field} must be a non-empty string array")
    for field in schema.get("object_arrays", ()):
        value = event.get(field)
        if value is None:
            if field in required:
                raise SystemExit(f"ERROR: {event_type} field {field} must be an object array")
            continue
        if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
            raise SystemExit(f"ERROR: {event_type} field {field} must be an object array")
    for field in schema.get("finding_arrays", ()):
        value = event.get(field)
        if value is None:
            if field in required:
                raise SystemExit(f"ERROR: {event_type} field {field} must be a finding array")
            continue
        validate_blocking_findings(event_type, field, value)
    for field in schema.get("scalar_maps", ()):
        value = event.get(field)
        if value is not None and not isinstance(value, dict):
            raise SystemExit(f"ERROR: {event_type} field {field} must be an object")
        if isinstance(value, dict):
            for key, item in value.items():
                if not isinstance(key, str) or not isinstance(item, (int, float, str, bool, type(None))):
                    raise SystemExit(f"ERROR: {event_type} field {field} must map strings to scalar values")
    for field in schema.get("run_meta_configs", ()):
        value = event.get(field)
        if value is None:
            continue
        if not isinstance(value, dict):
            raise SystemExit(f"ERROR: {event_type} field {field} must be an object or null")
        unknown = sorted(key for key in value if key not in RUN_META_CONFIG_FIELDS)
        if unknown:
            raise SystemExit(f"ERROR: {event_type} field {field} has unknown key(s): {', '.join(unknown)}")
        for key, item in value.items():
            if key in RUN_META_CONFIG_BOOLEAN_FIELDS:
                if item is not None and not isinstance(item, bool):
                    raise SystemExit(f"ERROR: {event_type} field {field}.{key} must be a boolean or null")
            elif item is not None and not isinstance(item, str):
                raise SystemExit(f"ERROR: {event_type} field {field}.{key} must be a string or null")


def validate_blocking_findings(event_type: str, field: str, value: object) -> None:
    if not isinstance(value, list):
        raise SystemExit(f"ERROR: {event_type} field {field} must be a finding array")
    for item in value:
        if not isinstance(item, dict):
            raise SystemExit(f"ERROR: {event_type} field {field} must be a finding array")
        unknown = sorted(key for key in item if key not in BLOCKING_FINDING_FIELDS)
        if unknown:
            raise SystemExit(f"ERROR: {event_type} field {field} has unknown key(s): {', '.join(unknown)}")
        for key in BLOCKING_FINDING_REQUIRED_STRINGS:
            if not isinstance(item.get(key), str) or not item.get(key):
                raise SystemExit(f"ERROR: {event_type} field {field}.{key} must be a non-empty string")
        for key in BLOCKING_FINDING_STRING_FIELDS:
            if key not in item or key in BLOCKING_FINDING_REQUIRED_STRINGS:
                continue
            if not isinstance(item[key], str) or not item[key]:
                raise SystemExit(f"ERROR: {event_type} field {field}.{key} must be a non-empty string")
        severity = item.get("severity")
        if severity is not None and (not isinstance(severity, str) or severity not in FINDING_SEVERITY_ORDER):
            allowed = ", ".join(FINDING_SEVERITY_ORDER)
            raise SystemExit(f"ERROR: {event_type} blocking_findings severity must be one of: {allowed}")
        file_refs = item.get("file_refs")
        if file_refs is not None and (
            not isinstance(file_refs, list) or not all(isinstance(ref, str) and ref for ref in file_refs)
        ):
            raise SystemExit(f"ERROR: {event_type} field {field}.file_refs must be a string array")
        min_repro_attempts = item.get("min_repro_attempts")
        if min_repro_attempts is not None and (type(min_repro_attempts) is not int or min_repro_attempts < 1):
            raise SystemExit(f"ERROR: {event_type} field {field}.min_repro_attempts must be an integer >= 1")


def validate_typed_event(event_type: str, event: dict[str, object], schema: dict[str, object]) -> None:
    if schema.get("timestamp"):
        event.setdefault("recorded_at", utc_now())
    if event_type == "consensus" and "outcome" not in event and "status" in event:
        mapped_outcome = LEGACY_CONSENSUS_STATUS_OUTCOMES.get(str(event.get("status")))
        if mapped_outcome:
            event["outcome"] = mapped_outcome
    if event_type == "gate_result" and "ok" not in event and isinstance(event.get("passed"), bool):
        event["ok"] = event["passed"]

    missing = [field for field in schema.get("required", ()) if field not in event]
    if missing:
        raise SystemExit(f"ERROR: {event_type} event missing required field(s): {', '.join(missing)}")
    unknown = sorted(field for field in event if field not in event_schema_fields(schema))
    if unknown:
        raise SystemExit(f"ERROR: {event_type} event has unknown field(s): {', '.join(unknown)}")

    validate_string_fields(event_type, event, schema)
    validate_enum_fields(event_type, event, schema)
    validate_typed_fields(event_type, event, schema)
    if event_type == "verification":
        for field in ("id", "finding_id"):
            if field in event and not event[field]:
                raise SystemExit(f"ERROR: verification field {field} must be a non-empty string")
        if "command_hash" in event and not COMMAND_HASH_PATTERN.match(str(event["command_hash"])):
            raise SystemExit("ERROR: verification field command_hash must be sha256:<64 hex digits>")

    if event_type == "consensus" and event.get("outcome") == "user_action_required":
        event.setdefault("requires_user", True)


def validate_ledger_event(event: dict[str, object]) -> None:
    event_type = event.get("type")
    if not isinstance(event_type, str) or not event_type:
        raise SystemExit("ERROR: ledger event type must be a non-empty string")
    recorded_at = event.get("recorded_at")
    if recorded_at is not None and not isinstance(recorded_at, str):
        raise SystemExit("ERROR: ledger event recorded_at must be a string")
    if event_type in LEDGER_EVENT_SCHEMAS:
        validate_typed_event(event_type, event, LEDGER_EVENT_SCHEMAS[event_type])
    else:
        event.setdefault("recorded_at", utc_now())
