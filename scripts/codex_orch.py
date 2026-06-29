#!/usr/bin/env python3
from __future__ import annotations

import argparse
import fnmatch
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from codex_orch_contract import (
    ALLOWED_LEGACY_CONSENSUS_STATUSES,
    ALLOWED_RISK_LEVELS,
    ALLOWED_VERIFICATION_KINDS,
    ALLOWED_VERIFICATION_RESULTS,
    CONSENSUS_OUTCOME_ORDER,
    DISPATCH_MODE_ORDER,
    LEGACY_CONSENSUS_STATUS_OUTCOMES,
    REVIEW_KIND_ORDER,
    RUN_META_CONFIG_BOOLEAN_FIELDS,
    RUN_META_CONFIG_FIELDS,
    SESSION_STATUS_ORDER,
    STATE_STATUS_ORDER,
    TASK_STATUS_ORDER,
)
from codex_orch_report import (
    is_final_review_verification,
    latest_record,
    prompt_log_pairs_complete,
    report_completeness_score,
    render_report,
    strict_report_missing_evidence,
)


PROTOCOL_VERSION = "1.0"
SCHEMA_VERSION = "1.0"
RUN_SUBDIRS = ("prompts", "logs", "artifacts")
UNSET = object()


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def print_json(payload: object) -> None:
    print(json.dumps(payload, indent=2, sort_keys=True))


def run_id_type(value: str) -> str:
    if not value or value in {".", ".."} or "/" in value or "\\" in value:
        raise argparse.ArgumentTypeError("run id must be a single path segment")
    return value


def name_type(value: str) -> str:
    if not value or value in {".", ".."} or "/" in value or "\\" in value:
        raise argparse.ArgumentTypeError("name must be a single path segment")
    return value


def repo_root(repo: str) -> Path:
    return Path(repo).expanduser().resolve()


def plugin_root() -> Path:
    return Path(__file__).resolve().parent.parent


def run_dir(repo: str, run_id: str) -> Path:
    return repo_root(repo) / ".codex-orchestrator" / "runs" / run_id


def state_path(directory: Path) -> Path:
    return directory / "state.json"


def ledger_path(directory: Path) -> Path:
    return directory / "ledger.jsonl"


def report_path(directory: Path) -> Path:
    return directory / "report.md"


def benchmark_path(directory: Path) -> Path:
    return directory / "benchmark.json"


def run_subdir(directory: Path, name: str) -> Path:
    return directory / name


def atomic_write_text(path: Path, text: str) -> None:
    tmp_path = path.with_name(f".{path.name}.tmp")
    tmp_path.write_text(text, encoding="utf-8")
    os.replace(tmp_path, path)


def write_text(path: Path, text: str, *, force: bool = False) -> bool:
    if path.exists() and not force:
        return False
    atomic_write_text(path, text)
    return True


def write_json(path: Path, payload: object, *, force: bool = False) -> bool:
    return write_text(path, json.dumps(payload, indent=2, sort_keys=True) + "\n", force=force)


def load_json(path: Path) -> dict[str, object]:
    if not path.exists():
        raise SystemExit(f"ERROR: missing run state: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SystemExit(f"ERROR: invalid JSON in {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise SystemExit(f"ERROR: run state must be a JSON object: {path}")
    return payload


def read_jsonl(path: Path) -> list[dict[str, object]]:
    records, _diagnostics = read_jsonl_with_warnings(path)
    return records


def read_jsonl_with_warnings(path: Path) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    records: list[dict[str, object]] = []
    diagnostics: list[dict[str, object]] = []
    if not path.exists():
        return records, diagnostics
    for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError as exc:
            diagnostics.append({"line_no": line_no, "error": str(exc)})
            continue
        if isinstance(record, dict):
            records.append(record)
    return records, diagnostics


def encode_jsonl_record(record: dict[str, object]) -> str:
    return json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n"


def append_jsonl(path: Path, record: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = encode_jsonl_record(record).encode("utf-8")
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
    try:
        written = os.write(fd, encoded)
        if written != len(encoded):
            raise OSError(f"short write to {path}: {written} of {len(encoded)} bytes")
        os.fsync(fd)
    finally:
        os.close(fd)


def initial_state(repo: Path, run_id: str) -> dict[str, object]:
    return {
        "run_id": run_id,
        "repo": str(repo),
        "created_at": utc_now(),
        "status": "active",
        "sessions": [],
    }


def initial_report_text() -> str:
    return (
        "# Report\n\n"
        "## Summary\n\n"
        "## Reproducibility\n\n"
        "## Changes\n\n"
        "## Evidence\n\n"
        "## Consensus\n\n"
        "## Gate Result\n\n"
        "## Risks / Follow-ups\n\n"
    )


def ensure_run_scaffold(repo: Path, run_id: str, *, force: bool = False) -> tuple[Path, dict[str, bool]]:
    directory = repo / ".codex-orchestrator" / "runs" / run_id
    directory.mkdir(parents=True, exist_ok=True)
    created = {
        "state.json": write_json(state_path(directory), initial_state(repo, run_id), force=force),
        "ledger.jsonl": write_text(ledger_path(directory), "", force=force),
        "report.md": write_text(report_path(directory), initial_report_text(), force=force),
    }
    for name in RUN_SUBDIRS:
        subdir = run_subdir(directory, name)
        already_exists = subdir.exists()
        subdir.mkdir(parents=True, exist_ok=True)
        created[f"{name}/"] = not already_exists
    return directory, created


def ledger_records(directory: Path, record_type: str | None = None) -> list[dict[str, object]]:
    records = read_jsonl(ledger_path(directory))
    if record_type is None:
        return records
    return [record for record in records if record.get("type") == record_type]


def records_of_type(records: list[dict[str, object]], record_type: str) -> list[dict[str, object]]:
    return [record for record in records if record.get("type") == record_type]


def latest_verification(directory: Path) -> dict[str, object] | None:
    records = ledger_records(directory, "verification")
    return records[-1] if records else None


def latest_verification_from_records(records: list[dict[str, object]]) -> dict[str, object] | None:
    verifications = records_of_type(records, "verification")
    return verifications[-1] if verifications else None


def ledger_warning_messages(diagnostics: list[dict[str, object]]) -> list[str]:
    if not diagnostics:
        return []
    messages = [f"Ledger contains {len(diagnostics)} malformed JSON line(s)."]
    for diagnostic in diagnostics:
        line_no = diagnostic.get("line_no")
        error = diagnostic.get("error")
        messages.append(f"ledger.jsonl line {line_no}: {error}")
    return messages


def load_event(raw: str) -> dict[str, object]:
    try:
        event = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"ERROR: event is not valid JSON: {exc}") from exc
    if not isinstance(event, dict):
        raise SystemExit("ERROR: event must be a JSON object")
    return event


LEDGER_EVENT_SCHEMAS = {
    "verification": {
        "timestamp": True,
        "required": ("type", "kind", "result", "recorded_at", "summary"),
        "strings": ("type", "recorded_at", "summary", "command", "notes"),
        "enums": {
            "kind": ALLOWED_VERIFICATION_KINDS,
            "result": ALLOWED_VERIFICATION_RESULTS,
        },
        "ints": ("exit_code",),
        "bools": ("stochastic",),
        "string_arrays": ("artifacts",),
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
        },
        "bools": ("requires_user",),
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
        "strings": ("type", "id", "title", "owner", "recorded_at"),
        "enums": {"status": TASK_STATUS_ORDER},
        "string_arrays": (
            "depends_on",
            "files_allowed",
            "files_forbidden",
            "acceptance",
            "verification_required",
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
        "string_arrays": ("findings",),
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
        "bools",
        "string_arrays",
        "non_empty_string_arrays",
        "object_arrays",
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


def run_git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True)


def default_branch(name: str) -> str:
    if name.startswith("codex-") and len(name) > len("codex-"):
        return f"codex/{name[len('codex-'):]}"
    return f"codex/{name}"


def find_active_state(repo: Path) -> Path:
    runs_dir = repo / ".codex-orchestrator" / "runs"
    candidates: list[Path] = []
    if runs_dir.exists():
        for path in runs_dir.glob("*/state.json"):
            try:
                state = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if isinstance(state, dict) and state.get("status") == "active":
                candidates.append(path)
    if not candidates:
        raise SystemExit("ERROR: no active run state found under .codex-orchestrator/runs")
    return max(candidates, key=lambda path: path.stat().st_mtime)


def upsert_session(
    path: Path,
    *,
    name: str,
    thread_id: str,
    mode: str,
    branch: str,
    worktree: Path,
) -> None:
    state = load_json(path)
    sessions = state.setdefault("sessions", [])
    if not isinstance(sessions, list):
        raise SystemExit(f"ERROR: sessions must be a list in {path}")
    session = {
        "name": name,
        "thread_id": thread_id,
        "mode": mode,
        "rollout_path": None,
        "branch": branch,
        "worktree": str(worktree),
        "status": "idle",
        "last_seen_at": utc_now(),
    }
    for index, existing in enumerate(sessions):
        if isinstance(existing, dict) and existing.get("name") == name:
            sessions[index] = {**existing, **session}
            break
    else:
        sessions.append(session)
    write_json(path, state, force=True)


def collect_warnings(
    state: dict[str, object],
    ledger_diagnostics: list[dict[str, object]] | None = None,
) -> list[str]:
    warnings: list[str] = []
    sessions = state.get("sessions")
    if isinstance(sessions, list):
        for session in sessions:
            if not isinstance(session, dict):
                continue
            name = session.get("name", "<unnamed>")
            if session.get("status") == "unknown":
                warnings.append(f"Session {name} has unknown status.")
            if session.get("parse_confidence") == "low":
                warnings.append(f"Session {name} has low parser confidence.")
    if ledger_diagnostics:
        warnings.extend(ledger_warning_messages(ledger_diagnostics))
    return warnings


def recommended_next_action(
    state: dict[str, object],
    verification: dict[str, object] | None,
    warnings: list[str] | None = None,
) -> str:
    active_warnings = warnings if warnings is not None else collect_warnings(state)
    if active_warnings:
        return "Inspect parser warnings or raw logs before trusting session status."
    if verification is None:
        return "Review the diff and record verification evidence."
    if state.get("status") not in {"complete", "accepted", "rejected"}:
        return "Finish review and update the run status or final report."
    return "No further action recorded."


def detect_git_sha(repo: Path) -> str | None:
    try:
        result = subprocess.run(
            ["git", "-C", str(repo), "rev-parse", "HEAD"],
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
    except OSError:
        return None
    if result.returncode != 0:
        return None
    sha = result.stdout.strip()
    return sha or None


def detect_plugin_version(root: Path) -> str | None:
    plugin_json = root / ".claude-plugin" / "plugin.json"
    if not plugin_json.exists():
        return None
    try:
        payload = json.loads(plugin_json.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    version = payload.get("version")
    return version if isinstance(version, str) and version else None


def detect_command_version(command: str) -> str | None:
    if shutil.which(command) is None:
        return None
    try:
        result = subprocess.run(
            [command, "--version"],
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    output = (result.stdout or result.stderr).strip()
    return output.splitlines()[0] if output else None


def default_run_config() -> dict[str, object]:
    return {
        "session_reuse_policy": None,
        "require_final_codex_review": None,
        "require_file_claims": None,
    }


def build_run_meta(
    *,
    repo: Path,
    run_id: str,
    plugin_ref: str | None = None,
    benchmark_suite: str | None = None,
    benchmark_case_id: str | None = None,
) -> dict[str, object]:
    repo_commit = detect_git_sha(repo)
    plugin_checkout = plugin_root()
    record: dict[str, object] = {
        "type": "run_meta",
        "recorded_at": utc_now(),
        "run_id": run_id,
        "plugin_version": detect_plugin_version(plugin_checkout),
        "plugin_git_sha": plugin_ref or detect_git_sha(plugin_checkout),
        "protocol_version": PROTOCOL_VERSION,
        "schema_version": SCHEMA_VERSION,
        "claude_code_version": None,
        "codex_cli_version": detect_command_version("codex"),
        "repo_commit": repo_commit,
        "benchmark_suite": benchmark_suite,
        "benchmark_case_id": benchmark_case_id,
        "config": default_run_config(),
    }
    validate_ledger_event(record)
    return record


def upsert_run_meta(path: Path, run_meta: dict[str, object]) -> dict[str, object]:
    path.parent.mkdir(parents=True, exist_ok=True)
    existing_lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    output_lines: list[str] = []
    replaced = False
    removed_duplicates = 0
    encoded = encode_jsonl_record(run_meta).rstrip("\n")
    for line in existing_lines:
        if not line.strip():
            output_lines.append(line)
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            output_lines.append(line)
            continue
        if isinstance(record, dict) and record.get("type") == "run_meta":
            if not replaced:
                output_lines.append(encoded)
                replaced = True
            else:
                removed_duplicates += 1
            continue
        output_lines.append(line)
    if not replaced:
        output_lines.append(encoded)
    atomic_write_text(path, "\n".join(output_lines) + "\n")
    return {
        "action": "updated" if replaced else "created",
        "removed_duplicates": removed_duplicates,
    }


def command_init(args: argparse.Namespace) -> int:
    repo = repo_root(args.repo)
    if not repo.exists() or not repo.is_dir():
        raise SystemExit(f"ERROR: repo does not exist or is not a directory: {repo}")

    directory, created = ensure_run_scaffold(repo, args.run_id, force=args.force)
    print_json({"ok": True, "run_id": args.run_id, "run_dir": str(directory), "created_or_replaced": created})
    return 0


def command_ensure_run(args: argparse.Namespace) -> int:
    repo = repo_root(args.repo)
    if not repo.exists() or not repo.is_dir():
        raise SystemExit(f"ERROR: repo does not exist or is not a directory: {repo}")

    directory, created = ensure_run_scaffold(repo, args.run_id, force=False)
    run_meta = build_run_meta(
        repo=repo,
        run_id=args.run_id,
        plugin_ref=args.plugin_ref,
        benchmark_suite=args.benchmark_suite,
        benchmark_case_id=args.benchmark_case_id,
    )
    upsert = upsert_run_meta(ledger_path(directory), run_meta)
    print_json(
        {
            "ok": True,
            "run_id": args.run_id,
            "run_dir": str(directory),
            "created_or_replaced": created,
            "run_meta_action": upsert["action"],
            "removed_run_meta_duplicates": upsert["removed_duplicates"],
            "run_meta": run_meta,
        }
    )
    return 0


def command_add_verification(args: argparse.Namespace) -> int:
    directory = run_dir(args.repo, args.run_id)
    load_json(state_path(directory))
    record: dict[str, object] = {
        "type": "verification",
        "recorded_at": utc_now(),
        "kind": args.kind,
        "result": args.result,
        "summary": args.summary,
    }
    if args.command:
        record["command"] = args.command
    if args.exit_code is not None:
        record["exit_code"] = args.exit_code
    if args.artifact:
        record["artifacts"] = args.artifact
    if args.notes:
        record["notes"] = args.notes
    append_jsonl(ledger_path(directory), record)
    print_json({"ok": True, "verification": record})
    return 0


def command_append_event(args: argparse.Namespace) -> int:
    directory = run_dir(args.repo, args.run_id)
    load_json(state_path(directory))
    raw_event = args.event_option if args.event_option is not None else args.event_json
    if raw_event is None:
        raw_event = sys.stdin.read()
    raw_event = raw_event.strip()
    if not raw_event:
        raise SystemExit("ERROR: no event JSON provided")
    event = load_event(raw_event)
    event.setdefault("type", "event")
    validate_ledger_event(event)
    append_jsonl(ledger_path(directory), event)
    print_json({"ok": True, "ledger_path": str(ledger_path(directory)), "event": event})
    return 0


def command_claim_files(args: argparse.Namespace) -> int:
    directory = run_dir(args.repo, args.run_id)
    load_json(state_path(directory))
    record: dict[str, object] = {
        "type": "file_claimed",
        "task_id": args.task_id,
        "agent": args.agent,
        "allow": args.allow,
    }
    if args.forbid:
        record["forbid"] = args.forbid
    validate_ledger_event(record)
    append_jsonl(ledger_path(directory), record)
    print_json({"ok": True, "ledger_path": str(ledger_path(directory)), "event": record})
    return 0


TERMINAL_TASK_STATUSES = {"complete", "blocked", "failed"}
GLOB_META_CHARS = "*?["


def normalize_glob(pattern: str) -> str:
    normalized = pattern.replace("\\", "/").strip()
    while normalized.startswith("./"):
        normalized = normalized[2:]
    return normalized


def has_glob_meta(pattern: str) -> bool:
    return any(char in pattern for char in GLOB_META_CHARS)


def glob_literal_prefix(pattern: str) -> str:
    positions = [pattern.find(char) for char in GLOB_META_CHARS if char in pattern]
    return pattern[: min(positions)] if positions else pattern


def glob_literal_dir_prefix(pattern: str) -> str:
    parts: list[str] = []
    for part in normalize_glob(pattern).split("/"):
        if has_glob_meta(part):
            break
        parts.append(part)
    return "/".join(parts)


def glob_sample(pattern: str) -> str:
    output: list[str] = []
    index = 0
    while index < len(pattern):
        char = pattern[index]
        if char == "*":
            if index + 1 < len(pattern) and pattern[index + 1] == "*":
                index += 1
            output.append("sample")
        elif char == "?":
            output.append("x")
        elif char == "[":
            close = pattern.find("]", index + 1)
            if close == -1:
                output.append(char)
            else:
                choices = pattern[index + 1 : close].lstrip("!^")
                output.append(choices[:1] or "x")
                index = close
        else:
            output.append(char)
        index += 1
    sample = "".join(output)
    return sample + "sample" if sample.endswith("/") else sample


def is_path_prefix(prefix: str, path: str) -> bool:
    prefix = prefix.rstrip("/")
    return bool(prefix) and (path == prefix or path.startswith(f"{prefix}/"))


def dir_prefixes_overlap(first: str, second: str) -> bool:
    if not first or not second:
        return True
    return is_path_prefix(first, second) or is_path_prefix(second, first)


def glob_patterns_overlap(first: str, second: str) -> bool:
    first = normalize_glob(first)
    second = normalize_glob(second)
    if not first or not second:
        return False
    if first == second:
        return True

    first_sample = glob_sample(first)
    second_sample = glob_sample(second)
    if fnmatch.fnmatchcase(first_sample, second) or fnmatch.fnmatchcase(second_sample, first):
        return True

    first_has_meta = has_glob_meta(first)
    second_has_meta = has_glob_meta(second)
    if not first_has_meta and not second_has_meta:
        return is_path_prefix(first, second) or is_path_prefix(second, first)
    if first_has_meta and second_has_meta:
        return dir_prefixes_overlap(glob_literal_dir_prefix(first), glob_literal_dir_prefix(second))
    if not first_has_meta:
        return fnmatch.fnmatchcase(first, second) or is_path_prefix(first, glob_literal_prefix(second))
    if not second_has_meta:
        return fnmatch.fnmatchcase(second, first) or is_path_prefix(second, glob_literal_prefix(first))
    return False


def terminal_claim_tasks(records: list[dict[str, object]]) -> set[str]:
    terminal_tasks: set[str] = set()
    for record in records:
        record_type = record.get("type")
        if record_type == "task_updated":
            task_id = record.get("id")
            status = record.get("status")
        elif record_type == "task_checkpoint":
            task_id = record.get("task_id")
            status = record.get("status")
        else:
            continue
        if isinstance(task_id, str) and task_id and status in TERMINAL_TASK_STATUSES:
            terminal_tasks.add(task_id)
    return terminal_tasks


def file_claim_conflict_report(records: list[dict[str, object]]) -> dict[str, object]:
    terminal_tasks = terminal_claim_tasks(records)
    claims_by_task: dict[str, list[str]] = {}
    for record in records:
        if record.get("type") != "file_claimed":
            continue
        task_id = record.get("task_id")
        allow = record.get("allow")
        if not isinstance(task_id, str) or not task_id or not isinstance(allow, list):
            continue
        if task_id in terminal_tasks:
            continue
        task_claims = claims_by_task.setdefault(task_id, [])
        task_claims.extend(pattern for pattern in allow if isinstance(pattern, str) and pattern)

    conflicts: list[dict[str, object]] = []
    task_ids = sorted(claims_by_task)
    for left_index, task_a in enumerate(task_ids):
        for task_b in task_ids[left_index + 1 :]:
            overlap = [
                {"allow_a": pattern_a, "allow_b": pattern_b}
                for pattern_a in claims_by_task[task_a]
                for pattern_b in claims_by_task[task_b]
                if glob_patterns_overlap(pattern_a, pattern_b)
            ]
            if overlap:
                conflicts.append({"task_a": task_a, "task_b": task_b, "overlap": overlap})
    return {"ok": not conflicts, "conflicts": conflicts}


def command_check_conflicts(args: argparse.Namespace) -> int:
    directory = run_dir(args.repo, args.run_id)
    load_json(state_path(directory))
    report = file_claim_conflict_report(read_jsonl(ledger_path(directory)))
    print_json(report)
    return 0 if report["ok"] else 1


UNRESOLVED_VERIFICATION_RESULTS = {"failed", "inconclusive", "needs_human_review"}
RESOLVING_CONSENSUS_OUTCOMES = {"consensus", "claude_decision"}
GENERIC_LEDGER_EVENT_TYPES = {"change", "event", "session_dispatch"}


def text_value(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


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


def requirement_satisfied(records: list[dict[str, object]], task_id: str, requirement: str) -> bool:
    for record in records:
        if record.get("result") != "passed":
            continue
        record_type = record.get("type")
        if record_type == "verification":
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
            return True
        if is_final_review_verification(record) and record.get("result") == "passed":
            return True
    return False


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


def gate_blocking_reasons(directory: Path, records: list[dict[str, object]], diagnostics: list[dict[str, object]]) -> list[str]:
    blocking: list[str] = []
    for diagnostic in diagnostics:
        blocking.append(
            f"malformed-ledger: ledger.jsonl line {diagnostic.get('line_no')}: {diagnostic.get('error')}"
        )

    freshness_issue = report_freshness_issue(directory, records)
    if freshness_issue:
        blocking.append(freshness_issue)

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


def command_gate(args: argparse.Namespace) -> int:
    directory = run_dir(args.repo, args.run_id)
    state = load_json(state_path(directory))
    records, diagnostics = read_jsonl_with_warnings(ledger_path(directory))
    blocking = gate_blocking_reasons(directory, records, diagnostics)
    payload = {
        "ok": not blocking,
        "blocking": blocking,
        "warnings": low_confidence_warnings(state),
    }
    record = {"type": "gate_result", "ok": payload["ok"], "blocking": blocking, "warnings": payload["warnings"]}
    validate_ledger_event(record)
    append_jsonl(ledger_path(directory), record)
    print_json(payload)
    return 0 if payload["ok"] else 1


def task_has_verification(records: list[dict[str, object]], task_id: str) -> bool:
    for record in records:
        if record.get("type") == "verification":
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


def command_doctor(args: argparse.Namespace) -> int:
    directory = run_dir(args.repo, args.run_id)
    state = load_json(state_path(directory))
    records, diagnostics = read_jsonl_with_warnings(ledger_path(directory))
    issues = doctor_issues(directory, state, records, diagnostics)
    print_json({"ok": not issues, "issues": issues})
    return 0 if not issues else 1


def command_status(args: argparse.Namespace) -> int:
    directory = run_dir(args.repo, args.run_id)
    state = load_json(state_path(directory))
    sessions = state.get("sessions") if isinstance(state.get("sessions"), list) else []
    ledger, ledger_diagnostics = read_jsonl_with_warnings(ledger_path(directory))
    verification = latest_verification_from_records(ledger)
    warnings = collect_warnings(state, ledger_diagnostics)
    payload = {
        "run_id": state.get("run_id"),
        "status": state.get("status"),
        "repo": state.get("repo"),
        "session_count": len(sessions),
        "sessions": sessions[-5:],
        "latest_verification": verification,
        "warnings": warnings,
        "recommended_next_action": recommended_next_action(state, verification, warnings),
    }
    print_json(payload)
    return 0


def command_worktree(args: argparse.Namespace) -> int:
    repo = repo_root(args.repo)
    if not repo.exists() or not repo.is_dir():
        raise SystemExit(f"ERROR: repo does not exist or is not a directory: {repo}")
    branch = args.branch or default_branch(args.name)
    worktree = (
        Path(args.worktree).expanduser()
        if args.worktree
        else repo.parent / f"repo-{args.name}"
    ).resolve()
    state_file = state_path(run_dir(args.repo, args.run_id)) if args.run_id else find_active_state(repo)
    load_json(state_file)

    run_git(repo, "worktree", "add", str(worktree), "-b", branch, args.base)
    upsert_session(
        state_file,
        name=args.name,
        thread_id=args.thread_id or f"pending:{args.name}",
        mode=args.mode,
        branch=branch,
        worktree=worktree,
    )
    print_json({"ok": True, "branch": branch, "worktree": str(worktree), "state": str(state_file)})
    return 0


def command_report(args: argparse.Namespace) -> int:
    directory = run_dir(args.repo, args.run_id)
    state = load_json(state_path(directory))
    existing_report = report_path(directory).read_text(encoding="utf-8") if report_path(directory).exists() else ""
    ledger, ledger_diagnostics = read_jsonl_with_warnings(ledger_path(directory))
    path = report_path(directory)
    report = render_report(
        state=state,
        ledger=ledger,
        existing_report=existing_report,
        warnings=collect_warnings(state, ledger_diagnostics),
        generated_at=utc_now(),
    )
    atomic_write_text(path, report)
    missing = strict_report_missing_evidence(state=state, ledger=ledger, report=report) if args.strict else []
    payload = {"ok": not missing, "run_id": args.run_id, "report_path": str(path)}
    if missing:
        payload["missing"] = missing
    print_json(payload)
    return 1 if missing else 0


PROMPT_TEMPLATE_FILES = {
    "impl": "task-prompt.md",
    "review": "review-prompt.md",
}


def markdown_list(value: object) -> str:
    if isinstance(value, str) and value:
        return f"- {value}"
    if isinstance(value, list):
        items = [item for item in value if isinstance(item, str) and item]
        if items:
            return "\n".join(f"- {item}" for item in items)
    return "none"


def prompt_template_path(kind: str) -> Path:
    return plugin_root() / "templates" / PROMPT_TEMPLATE_FILES[kind]


def task_created_record(records: list[dict[str, object]], task_id: str) -> dict[str, object]:
    matches = [
        record
        for record in records
        if record.get("type") == "task_created" and record.get("id") == task_id
    ]
    if not matches:
        raise SystemExit(f"ERROR: no task_created record found for task id {task_id}")
    return matches[-1]


def prompt_context(record: dict[str, object]) -> dict[str, str]:
    title = text_value(record.get("title")) or ""
    goal = text_value(record.get("goal")) or text_value(record.get("summary")) or title
    return {
        "task_id": text_value(record.get("id")) or "",
        "title": title,
        "files_allowed": markdown_list(record.get("files_allowed")),
        "files_forbidden": markdown_list(record.get("files_forbidden")),
        "acceptance": markdown_list(record.get("acceptance")),
        "verification_required": markdown_list(record.get("verification_required")),
        "goal": goal,
    }


def render_prompt_template(template: str, context: dict[str, str]) -> str:
    rendered = template
    for key, value in context.items():
        rendered = rendered.replace(f"{{{{ {key} }}}}", value)
        rendered = rendered.replace(f"{{{{{key}}}}}", value)
    return rendered


def command_render_prompt(args: argparse.Namespace) -> int:
    directory = run_dir(args.repo, args.run_id)
    load_json(state_path(directory))
    record = task_created_record(read_jsonl(ledger_path(directory)), args.task_id)
    template_path = prompt_template_path(args.kind)
    if not template_path.exists():
        raise SystemExit(f"ERROR: missing prompt template: {template_path}")
    rendered = render_prompt_template(template_path.read_text(encoding="utf-8"), prompt_context(record))
    if args.out:
        output_path = Path(args.out).expanduser()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(output_path, rendered)
    else:
        sys.stdout.write(rendered)
    return 0


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
        "report_score",
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
    report_score = payload.get("report_score")
    if not isinstance(report_score, (int, float)) or not 0 <= report_score <= 1:
        raise SystemExit("ERROR: benchmark field report_score must be a number from 0 to 1")
    external_score = payload.get("external_score")
    if external_score is not None and not isinstance(external_score, dict):
        raise SystemExit("ERROR: benchmark field external_score must be an object or null")


def command_benchmark(args: argparse.Namespace) -> int:
    directory = run_dir(args.repo, args.run_id)
    state = load_json(state_path(directory))
    ledger, ledger_diagnostics = read_jsonl_with_warnings(ledger_path(directory))
    run_meta = latest_record(ledger, "run_meta") or {}
    repo = repo_root(args.repo)
    sessions = state.get("sessions") if isinstance(state.get("sessions"), list) else []
    gate_passed = latest_gate_passed(ledger)
    score = report_completeness_score(state, ledger)
    plugin_checkout = plugin_root()
    passed = args.passed if args.passed is not UNSET else gate_passed
    payload: dict[str, object] = {
        "suite": args.suite or string_or_none(run_meta.get("benchmark_suite")),
        "case_id": args.case_id or string_or_none(run_meta.get("benchmark_case_id")),
        "plugin_ref": args.plugin_ref or string_or_none(run_meta.get("plugin_git_sha")) or detect_git_sha(plugin_checkout),
        "repo_commit": string_or_none(run_meta.get("repo_commit")) or detect_git_sha(repo),
        "passed": passed,
        "wall_seconds": None,
        "claude_turns": None,
        "codex_sessions": len(sessions),
        "codex_reviews": sum(1 for record in ledger if is_final_review_verification(record)),
        "manual_interventions": None,
        "prompt_log_pairs_complete": prompt_log_pairs_complete(ledger),
        "ledger_errors": len(ledger_diagnostics),
        "gate_passed": gate_passed,
        "report_score": score["total"],
        "external_score": None,
    }
    validate_benchmark_result(payload)
    path = benchmark_path(directory)
    write_json(path, payload, force=True)
    print_json({"ok": True, "run_id": args.run_id, "benchmark_path": str(path), "benchmark": payload})
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Durable ledger CLI for Codex Orchestrator.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    init_parser = subparsers.add_parser("init", help="Create a run ledger.")
    init_parser.add_argument("--repo", required=True, help="Repository root for the run.")
    init_parser.add_argument("--run-id", required=True, type=run_id_type, help="Run id / directory name.")
    init_parser.add_argument("--force", action="store_true", help="Overwrite scaffold files.")
    init_parser.set_defaults(func=command_init)

    ensure_parser = subparsers.add_parser("ensure-run", help="Create a run scaffold and upsert run metadata.")
    ensure_parser.add_argument("--repo", default=".", help="Repository root.")
    ensure_parser.add_argument("--run-id", required=True, type=run_id_type, help="Run id / directory name.")
    ensure_parser.add_argument("--plugin-ref", help="Plugin git SHA or ref to record.")
    ensure_parser.add_argument("--benchmark-suite", help="Benchmark suite name.")
    ensure_parser.add_argument("--benchmark-case-id", help="Benchmark case id.")
    ensure_parser.set_defaults(func=command_ensure_run)

    status_parser = subparsers.add_parser("status", help="Print compact run status.")
    status_parser.add_argument("--repo", default=".", help="Repository root.")
    status_parser.add_argument("--run-id", required=True, type=run_id_type)
    status_parser.set_defaults(func=command_status)

    verification_parser = subparsers.add_parser("add-verification", help="Append verification evidence.")
    verification_parser.add_argument("--repo", default=".", help="Repository root.")
    verification_parser.add_argument("--run-id", required=True, type=run_id_type)
    verification_parser.add_argument("--kind", required=True, choices=ALLOWED_VERIFICATION_KINDS)
    verification_parser.add_argument("--result", required=True, choices=ALLOWED_VERIFICATION_RESULTS)
    verification_parser.add_argument("--summary", required=True)
    verification_parser.add_argument("--command")
    verification_parser.add_argument("--exit-code", type=int)
    verification_parser.add_argument("--artifact", action="append", default=[])
    verification_parser.add_argument("--notes")
    verification_parser.set_defaults(func=command_add_verification)

    append_parser = subparsers.add_parser("append-event", help="Append a schema-checked JSON event to ledger.jsonl.")
    append_parser.add_argument("--repo", default=".", help="Repository root.")
    append_parser.add_argument("--run-id", required=True, type=run_id_type)
    append_parser.add_argument("event_json", nargs="?", help="JSON object to append. If omitted, stdin is read.")
    append_parser.add_argument("--event", dest="event_option", help="JSON object to append.")
    append_parser.set_defaults(func=command_append_event)

    claim_parser = subparsers.add_parser("claim-files", help="Append a writable file-claim event.")
    claim_parser.add_argument("--repo", default=".", help="Repository root.")
    claim_parser.add_argument("--run-id", required=True, type=run_id_type)
    claim_parser.add_argument("--task-id", required=True)
    claim_parser.add_argument("--agent", required=True)
    claim_parser.add_argument("--allow", required=True, action="append", help="Writable glob. Repeat for multiple globs.")
    claim_parser.add_argument("--forbid", action="append", default=[], help="Forbidden glob. Repeat for multiple globs.")
    claim_parser.set_defaults(func=command_claim_files)

    conflicts_parser = subparsers.add_parser("check-conflicts", help="Check active file claims for writable overlap.")
    conflicts_parser.add_argument("--repo", default=".", help="Repository root.")
    conflicts_parser.add_argument("--run-id", required=True, type=run_id_type)
    conflicts_parser.set_defaults(func=command_check_conflicts)

    gate_parser = subparsers.add_parser("gate", help="Evaluate whether a run is ready for acceptance.")
    gate_parser.add_argument("--repo", default=".", help="Repository root.")
    gate_parser.add_argument("--run-id", required=True, type=run_id_type)
    gate_parser.set_defaults(func=command_gate)

    doctor_parser = subparsers.add_parser("doctor", help="Check run ledger integrity without mutating it.")
    doctor_parser.add_argument("--repo", default=".", help="Repository root.")
    doctor_parser.add_argument("--run-id", required=True, type=run_id_type)
    doctor_parser.set_defaults(func=command_doctor)

    worktree_parser = subparsers.add_parser("worktree", help="Create a Codex worktree and register it.")
    worktree_parser.add_argument("--name", required=True, type=name_type, help="Session name, for example codex-a.")
    worktree_parser.add_argument("--repo", default=".", help="Repository root.")
    worktree_parser.add_argument("--run-id", type=run_id_type, help="Run id. Defaults to newest active run.")
    worktree_parser.add_argument("--base", default="main", help="Base ref for the new branch.")
    worktree_parser.add_argument("--branch", help="Branch name. Defaults to codex/<name suffix>.")
    worktree_parser.add_argument("--worktree", help="Worktree path. Defaults to ../repo-<name>.")
    worktree_parser.add_argument("--thread-id", help="Thread id if already known.")
    worktree_parser.add_argument("--mode", choices=("ide", "exec"), default="exec")
    worktree_parser.set_defaults(func=command_worktree)

    report_parser = subparsers.add_parser("report", help="Generate report.md.")
    report_parser.add_argument("--repo", default=".", help="Repository root.")
    report_parser.add_argument("--run-id", required=True, type=run_id_type)
    report_parser.add_argument("--strict", action="store_true", help="Fail if required report evidence is missing.")
    report_parser.set_defaults(func=command_report)

    prompt_parser = subparsers.add_parser("render-prompt", help="Render a Codex task or review prompt.")
    prompt_parser.add_argument("--repo", default=".", help="Repository root.")
    prompt_parser.add_argument("--run-id", required=True, type=run_id_type)
    prompt_parser.add_argument("--task-id", required=True)
    prompt_parser.add_argument("--kind", required=True, choices=tuple(PROMPT_TEMPLATE_FILES))
    prompt_parser.add_argument("--out", help="Write the rendered prompt to this file instead of stdout.")
    prompt_parser.set_defaults(func=command_render_prompt)

    benchmark_parser = subparsers.add_parser("benchmark", help="Write benchmark.json for a run.")
    benchmark_parser.add_argument("--repo", default=".", help="Repository root.")
    benchmark_parser.add_argument("--run-id", required=True, type=run_id_type)
    benchmark_parser.add_argument("--suite", help="Benchmark suite name.")
    benchmark_parser.add_argument("--case-id", help="Benchmark case id.")
    benchmark_parser.add_argument("--plugin-ref", help="Plugin git SHA or ref.")
    benchmark_parser.add_argument(
        "--passed",
        default=UNSET,
        type=nullable_bool_type,
        help="Benchmark pass status: true, false, or null.",
    )
    benchmark_parser.set_defaults(func=command_benchmark)

    return parser


def main() -> int:
    args = build_parser().parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
