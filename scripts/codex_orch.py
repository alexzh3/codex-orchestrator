#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
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
    LEGACY_CONSENSUS_STATUS_OUTCOMES,
    TASK_STATUS_ORDER,
)
from codex_orch_report import render_report


RUN_SUBDIRS = ("prompts", "logs", "artifacts")


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


def run_dir(repo: str, run_id: str) -> Path:
    return repo_root(repo) / ".codex-orchestrator" / "runs" / run_id


def state_path(directory: Path) -> Path:
    return directory / "state.json"


def ledger_path(directory: Path) -> Path:
    return directory / "ledger.jsonl"


def report_path(directory: Path) -> Path:
    return directory / "report.md"


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
    records: list[dict[str, object]] = []
    if not path.exists():
        return records
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(record, dict):
            records.append(record)
    return records


def append_jsonl(path: Path, record: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = (json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
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


def ledger_records(directory: Path, record_type: str | None = None) -> list[dict[str, object]]:
    records = read_jsonl(ledger_path(directory))
    if record_type is None:
        return records
    return [record for record in records if record.get("type") == record_type]


def latest_verification(directory: Path) -> dict[str, object] | None:
    records = ledger_records(directory, "verification")
    return records[-1] if records else None


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
}


def event_schema_fields(schema: dict[str, object]) -> set[str]:
    fields: set[str] = set(schema.get("required", ()))
    for key in ("strings", "ints", "bools", "string_arrays", "non_empty_string_arrays", "scalar_maps"):
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
    for field in schema.get("ints", ()):
        value = event.get(field)
        if value is not None and type(value) is not int:
            raise SystemExit(f"ERROR: {event_type} field {field} must be an integer or null")
    for field in schema.get("bools", ()):
        value = event.get(field)
        if value is not None and not isinstance(value, bool):
            raise SystemExit(f"ERROR: {event_type} field {field} must be a boolean")
    for field in schema.get("string_arrays", ()):
        value = event.get(field)
        if value is not None and (
            not isinstance(value, list) or not all(isinstance(item, str) for item in value)
        ):
            raise SystemExit(f"ERROR: {event_type} field {field} must be a string array")
    for field in schema.get("non_empty_string_arrays", ()):
        value = event.get(field)
        if not isinstance(value, list) or not all(isinstance(item, str) and item for item in value):
            raise SystemExit(f"ERROR: {event_type} field {field} must be a non-empty string array")
    for field in schema.get("scalar_maps", ()):
        value = event.get(field)
        if value is not None and not isinstance(value, dict):
            raise SystemExit(f"ERROR: {event_type} field {field} must be an object")
        if isinstance(value, dict):
            for key, item in value.items():
                if not isinstance(key, str) or not isinstance(item, (int, float, str, bool, type(None))):
                    raise SystemExit(f"ERROR: {event_type} field {field} must map strings to scalar values")


def validate_typed_event(event_type: str, event: dict[str, object], schema: dict[str, object]) -> None:
    if schema.get("timestamp"):
        event.setdefault("recorded_at", utc_now())
    if event_type == "consensus" and "outcome" not in event and "status" in event:
        mapped_outcome = LEGACY_CONSENSUS_STATUS_OUTCOMES.get(str(event.get("status")))
        if mapped_outcome:
            event["outcome"] = mapped_outcome

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


def collect_warnings(state: dict[str, object]) -> list[str]:
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
    return warnings


def recommended_next_action(state: dict[str, object], verification: dict[str, object] | None) -> str:
    if collect_warnings(state):
        return "Inspect parser warnings or raw logs before trusting session status."
    if verification is None:
        return "Review the diff and record verification evidence."
    if state.get("status") not in {"complete", "accepted", "rejected"}:
        return "Finish review and update the run status or final report."
    return "No further action recorded."


def command_init(args: argparse.Namespace) -> int:
    repo = repo_root(args.repo)
    if not repo.exists() or not repo.is_dir():
        raise SystemExit(f"ERROR: repo does not exist or is not a directory: {repo}")

    directory = run_dir(args.repo, args.run_id)
    directory.mkdir(parents=True, exist_ok=True)
    created = {
        "state.json": write_json(state_path(directory), initial_state(repo, args.run_id), force=args.force),
        "ledger.jsonl": write_text(ledger_path(directory), "", force=args.force),
        "report.md": write_text(
            report_path(directory),
            (
                "# Report\n\n"
                "## Summary\n\n"
                "## Changes\n\n"
                "## Evidence\n\n"
                "## Consensus\n\n"
                "## Risks / Follow-ups\n\n"
            ),
            force=args.force,
        ),
    }
    for name in RUN_SUBDIRS:
        subdir = run_subdir(directory, name)
        already_exists = subdir.exists()
        subdir.mkdir(parents=True, exist_ok=True)
        created[f"{name}/"] = not already_exists
    print_json({"ok": True, "run_id": args.run_id, "run_dir": str(directory), "created_or_replaced": created})
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


def command_status(args: argparse.Namespace) -> int:
    directory = run_dir(args.repo, args.run_id)
    state = load_json(state_path(directory))
    sessions = state.get("sessions") if isinstance(state.get("sessions"), list) else []
    verification = latest_verification(directory)
    warnings = collect_warnings(state)
    payload = {
        "run_id": state.get("run_id"),
        "status": state.get("status"),
        "repo": state.get("repo"),
        "session_count": len(sessions),
        "sessions": sessions[-5:],
        "latest_verification": verification,
        "warnings": warnings,
        "recommended_next_action": recommended_next_action(state, verification),
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
    path = report_path(directory)
    atomic_write_text(
        path,
        render_report(
            state=state,
            ledger=ledger_records(directory),
            existing_report=existing_report,
            warnings=collect_warnings(state),
            generated_at=utc_now(),
        ),
    )
    print_json({"ok": True, "run_id": args.run_id, "report_path": str(path)})
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Durable ledger CLI for Codex Orchestrator.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    init_parser = subparsers.add_parser("init", help="Create a run ledger.")
    init_parser.add_argument("--repo", required=True, help="Repository root for the run.")
    init_parser.add_argument("--run-id", required=True, type=run_id_type, help="Run id / directory name.")
    init_parser.add_argument("--force", action="store_true", help="Overwrite scaffold files.")
    init_parser.set_defaults(func=command_init)

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

    return parser


def main() -> int:
    args = build_parser().parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
