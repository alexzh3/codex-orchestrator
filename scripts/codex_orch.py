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
    atomic_write_text(
        path,
        render_report(
            state=state,
            ledger=ledger,
            existing_report=existing_report,
            warnings=collect_warnings(state, ledger_diagnostics),
            generated_at=utc_now(),
        ),
    )
    print_json({"ok": True, "run_id": args.run_id, "report_path": str(path)})
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
    report_parser.set_defaults(func=command_report)

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
