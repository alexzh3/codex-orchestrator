#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

PARSER_VERSION = "0.1.0"
TAIL_LIMIT_BYTES = 500_000

LEDGER_EVENT_TYPES = {
    "run_started",
    "task",
    "execution",
    "execution_result",
    "verification",
    "decision",
    "run_closed",
}

TERMINAL_TASK_STATUSES = {"complete", "blocked", "failed"}
TERMINAL_EXECUTION_STATUSES = {"complete", "blocked", "failed"}
VERIFICATION_RESULTS = {"passed", "failed", "inconclusive", "skipped"}

EXEC_EVENT_TYPES = {
    "thread.started",
    "turn.started",
    "turn.completed",
    "turn.failed",
    "item.started",
    "item.updated",
    "item.completed",
    "error",
}

IDE_EVENT_TYPES = {
    "thread_goal_updated",
    "agent_message",
    "function_call",
    "function_call_output",
    "token_count",
    "message",
}

APPROVAL_HINTS = (
    "awaiting approval",
    "approval required",
    "needs approval",
    "outside the sandbox",
    "docker socket",
    "approve in",
)

FAILURE_HINTS = (
    "FAILED ",
    "Traceback (most recent",
)


@dataclass(frozen=True)
class EventRecord:
    event: dict[str, object]
    event_type: str


@dataclass(frozen=True)
class MonitorTarget:
    path: Path
    source: str
    agent: str | None = None
    execution: str | None = None


def json_dumps(payload: object) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def event_type(event: dict[str, object]) -> str:
    payload = event.get("payload")
    if isinstance(payload, dict) and isinstance(payload.get("type"), str):
        return str(payload["type"])
    if isinstance(event.get("type"), str):
        return str(event["type"])
    return "<missing>"


def iter_json_events(lines: Iterable[str]) -> Iterable[EventRecord]:
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        try:
            event = json.loads(stripped)
        except json.JSONDecodeError:
            yield EventRecord({"_parse_error": stripped[:200]}, "<invalid-json>")
            continue
        if not isinstance(event, dict):
            yield EventRecord(
                {"_parse_error": "top-level JSON value is not an object"}, "<non-object>"
            )
            continue
        yield EventRecord(event, event_type(event))


def read_lines(
    path: Path, source: str, *, since_offset: int | None = None
) -> tuple[list[str], int, int]:
    size = path.stat().st_size
    if since_offset is not None:
        start = max(0, min(since_offset, size))
    else:
        start = 0

    with path.open("r", encoding="utf-8") as handle:
        if source == "ide" and since_offset is None:
            handle.seek(max(0, size - TAIL_LIMIT_BYTES))
            start = handle.tell()
        else:
            handle.seek(start)
        if source == "ide" and since_offset is None and start > 0:
            handle.readline()
            start = handle.tell()
        lines = [line for line in handle]
        end = handle.tell()
    return lines, start, end


def known_types_for_source(source: str) -> set[str]:
    if source == "exec":
        return EXEC_EVENT_TYPES
    if source == "ide":
        return IDE_EVENT_TYPES
    return EXEC_EVENT_TYPES | IDE_EVENT_TYPES


def is_reconnect_notice(record: EventRecord) -> bool:
    if record.event_type != "error":
        return False
    text = json_dumps(record.event)
    return "reconnecting" in text.lower()


def compatibility(records: list[EventRecord], source: str) -> dict[str, object]:
    known = known_types_for_source(source)
    unknown = sorted(
        {
            record.event_type
            for record in records
            if record.event_type not in known and not is_reconnect_notice(record)
        }
    )
    known_count = sum(
        1 for record in records if record.event_type in known or is_reconnect_notice(record)
    )
    unknown_count = len(records) - known_count
    warnings: list[str] = []
    if not records:
        warnings.append("no events found")
    if source == "auto":
        warnings.append("source auto-detected from available events")
    parse_confidence = "low" if records and unknown_count > known_count else "high"
    return {
        "parser_version": PARSER_VERSION,
        "parse_confidence": parse_confidence,
        "unknown_event_types": unknown,
        "warnings": warnings,
    }


def incompatible_message() -> str:
    return (
        f"ERROR: Codex rollout/JSON format appears incompatible (parser {PARSER_VERSION}). "
        "Run --dump-event-types and update the parser. Do not infer session status."
    )


def find_rollout(thread_id: str, root: Path | None = None) -> Path | None:
    sessions_root = root or Path.home() / ".codex" / "sessions"
    if not sessions_root.exists():
        return None
    matches = [path for path in sessions_root.rglob(f"*{thread_id}*") if path.is_file()]
    if not matches:
        return None
    return max(matches, key=lambda path: path.stat().st_mtime)


def source_from_events(records: list[EventRecord]) -> str:
    counts = Counter(record.event_type for record in records)
    exec_score = sum(counts[event_type] for event_type in EXEC_EVENT_TYPES)
    ide_score = sum(counts[event_type] for event_type in IDE_EVENT_TYPES)
    if exec_score > ide_score:
        return "exec"
    if ide_score > exec_score:
        return "ide"
    return "exec"


def source_and_path(args: argparse.Namespace) -> tuple[str, Path | None, list[str]]:
    warnings: list[str] = []
    path = Path(args.file).expanduser() if args.file else None
    source = args.source or "auto"
    if path is None:
        path = find_rollout(args.thread_id)
        if path is None:
            warnings.append("no event source found; provide --file or check the thread id")
        elif source == "auto":
            source = "ide"
    if source == "auto" and path is not None:
        sample_lines, _, _ = read_lines(path, "ide")
        source = source_from_events(list(iter_json_events(sample_lines)))
    if source == "auto":
        source = "exec"
    return source, path, warnings


def event_text(event: dict[str, object]) -> str:
    payload = event.get("payload")
    if isinstance(payload, dict):
        for key in ("message", "text", "output"):
            value = payload.get(key)
            if isinstance(value, str):
                return value
    for key in ("message", "text", "error"):
        value = event.get(key)
        if isinstance(value, str):
            return value
    return json_dumps(event)


def classify_exec(records: list[EventRecord]) -> tuple[str, dict[str, object]]:
    status = "idle"
    usage: object = None
    error: object = None
    last_agent_text = ""
    thread_started = False
    for record in records:
        if record.event_type == "thread.started":
            thread_started = True
            status = "idle"
        elif record.event_type == "turn.started":
            status = "active"
        elif record.event_type == "turn.completed":
            status = "complete"
            usage = record.event.get("usage")
        elif record.event_type == "turn.failed":
            status = "failed"
            error = record.event.get("error")
        elif record.event_type == "error" and not is_reconnect_notice(record):
            status = "failed"
            error = record.event.get("error") or record.event.get("message")
        elif record.event_type == "item.completed":
            item = record.event.get("item")
            if isinstance(item, dict) and item.get("type") == "agent_message":
                text = item.get("text")
                if isinstance(text, str):
                    last_agent_text = text
    details: dict[str, object] = {}
    if usage is not None:
        details["usage"] = usage
    if error is not None:
        details["error"] = error
    if thread_started:
        details["thread_started"] = True
    if last_agent_text:
        details["last_agent_message"] = last_agent_text
    return status, details


def goal_status_to_session_status(goal_status: str | None) -> str | None:
    if goal_status is None:
        return None
    normalized = goal_status.lower()
    if normalized == "active":
        return "active"
    if normalized in {"complete", "completed", "done"}:
        return "complete"
    if normalized in {"failed", "error"}:
        return "failed"
    if normalized == "idle":
        return "idle"
    if normalized in {"blocked", "awaiting-approval"}:
        return "awaiting-approval"
    return "idle"


def classify_ide(records: list[EventRecord], path: Path | None) -> tuple[str, dict[str, object]]:
    goal_status: str | None = None
    goal_text: str | None = None
    last_agent_text = ""
    saw_failure = False

    for record in records:
        text = event_text(record.event)
        if any(hint in text for hint in FAILURE_HINTS):
            saw_failure = True
        if record.event_type == "thread_goal_updated":
            payload = record.event.get("payload")
            payload_dict = payload if isinstance(payload, dict) else record.event
            goal = payload_dict.get("goal") if isinstance(payload_dict, dict) else None
            if isinstance(goal, dict):
                status_value = goal.get("status")
                text_value = goal.get("text")
                goal_status = str(status_value) if status_value is not None else goal_status
                goal_text = str(text_value) if text_value is not None else goal_text
        elif record.event_type == "agent_message":
            last_agent_text = text

    status = goal_status_to_session_status(goal_status) or "idle"
    if saw_failure:
        status = "failed"
    if status in {"active", "idle"} and any(
        hint in last_agent_text.lower() for hint in APPROVAL_HINTS
    ):
        if path is None or time.time() - path.stat().st_mtime > 600:
            status = "awaiting-approval"
    elif status == "active" and path is not None and time.time() - path.stat().st_mtime > 600:
        status = "idle"

    details: dict[str, object] = {}
    if goal_status is not None:
        details["goal_status"] = goal_status
    if goal_text:
        details["goal_text"] = goal_text
    if last_agent_text:
        details["last_agent_message"] = last_agent_text
    if path is not None:
        details["idle_seconds"] = int(time.time() - path.stat().st_mtime)
    return status, details


def load_records(path: Path | None, source: str) -> tuple[list[EventRecord], int, int]:
    if path is None:
        return [], 0, 0
    lines, start, end = read_lines(path, source)
    return list(iter_json_events(lines)), start, end


def command_find(args: argparse.Namespace) -> int:
    path = Path(args.file).expanduser() if args.file else find_rollout(args.thread_id)
    source = args.source or ("ide" if path else "exec")
    if args.dump_event_types:
        records, start, end = load_records(path, source)
        counts = Counter(record.event_type for record in records)
        payload = {
            "thread_id": args.thread_id,
            "source": source,
            "path": str(path) if path else None,
            "event_types": dict(sorted(counts.items())),
            "compatibility": compatibility(records, source),
            "offset": start,
            "next_offset": end,
        }
        print(json_dumps(payload) if args.json else payload)
        return 2 if payload["compatibility"]["parse_confidence"] == "low" else 0
    if args.json:
        print(
            json_dumps(
                {"thread_id": args.thread_id, "source": source, "path": str(path) if path else None}
            )
        )
    elif path:
        print(path)
    if path is None:
        return 1
    return 0


def command_state(args: argparse.Namespace) -> int:
    source, path, source_warnings = source_and_path(args)
    records, start, end = load_records(path, source)
    compat = compatibility(records, source)
    compat["warnings"] = [*compat["warnings"], *source_warnings]

    if args.dump_event_types:
        counts = Counter(record.event_type for record in records)
        payload = {
            "thread_id": args.thread_id,
            "source": source,
            "path": str(path) if path else None,
            "event_types": dict(sorted(counts.items())),
            "compatibility": compat,
        }
        print(json_dumps(payload) if args.json else payload)
        return 2 if compat["parse_confidence"] == "low" else 0

    if compat["parse_confidence"] == "low":
        payload = {
            "thread_id": args.thread_id,
            "source": source,
            "path": str(path) if path else None,
            "status": "unknown",
            "compatibility": compat,
            "offset": start,
            "next_offset": end,
        }
        print(json_dumps(payload) if args.json else payload)
        print(incompatible_message(), file=sys.stderr)
        return 2

    if source == "exec":
        status, details = classify_exec(records)
    else:
        status, details = classify_ide(records, path)

    payload = {
        "thread_id": args.thread_id,
        "source": source,
        "path": str(path) if path else None,
        "status": status,
        "details": details,
        "compatibility": compat,
        "offset": start,
        "next_offset": end,
    }
    print(json_dumps(payload) if args.json else payload)
    return 0


def command_tail(args: argparse.Namespace) -> int:
    source, path, source_warnings = source_and_path(args)
    if path is None:
        payload = {
            "thread_id": args.thread_id,
            "source": source,
            "path": None,
            "events": [],
            "offset": 0,
            "next_offset": 0,
            "compatibility": {
                "parser_version": PARSER_VERSION,
                "parse_confidence": "high",
                "unknown_event_types": [],
                "warnings": source_warnings,
            },
        }
        print(json_dumps(payload) if args.json else "")
        return 1

    lines, start, end = read_lines(path, source, since_offset=args.since_offset)
    records = list(iter_json_events(lines))
    compat = compatibility(records, source)
    compat["warnings"] = [*compat["warnings"], *source_warnings]
    if args.dump_event_types:
        counts = Counter(record.event_type for record in records)
        payload = {
            "thread_id": args.thread_id,
            "source": source,
            "path": str(path),
            "event_types": dict(sorted(counts.items())),
            "compatibility": compat,
        }
        print(json_dumps(payload) if args.json else payload)
        return 2 if compat["parse_confidence"] == "low" else 0
    if args.json:
        payload = {
            "thread_id": args.thread_id,
            "source": source,
            "path": str(path),
            "events": [record.event for record in records],
            "offset": start,
            "next_offset": end,
            "compatibility": compat,
        }
        print(json_dumps(payload))
    else:
        for line in lines:
            print(line, end="")
    if compat["parse_confidence"] == "low":
        print(incompatible_message(), file=sys.stderr)
        return 2
    return 0


def read_ledger(path: Path) -> tuple[list[dict[str, object]], list[str]]:
    records: list[dict[str, object]] = []
    issues: list[str] = []
    if not path.exists():
        return records, [f"missing ledger: {path}"]
    try:
        with path.open("r", encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, start=1):
                stripped = line.strip()
                if not stripped:
                    continue
                try:
                    value = json.loads(stripped)
                except json.JSONDecodeError as exc:
                    issues.append(f"line {line_number}: invalid JSON: {exc.msg}")
                    continue
                if not isinstance(value, dict):
                    issues.append(f"line {line_number}: ledger record must be an object")
                    continue
                value["_line"] = line_number
                records.append(value)
    except OSError as exc:
        issues.append(f"could not read ledger: {exc}")
    return records, issues


def record_line(record: dict[str, object]) -> str:
    line = record.get("_line")
    return f"line {line}" if isinstance(line, int) else "ledger"


def execution_key(record: dict[str, object]) -> tuple[str, str] | None:
    agent = record.get("agent")
    execution = record.get("execution")
    if isinstance(agent, str) and agent and isinstance(execution, str) and execution:
        return agent, execution
    return None


def display_execution(key: tuple[str, str]) -> str:
    return f"{key[0]}/{key[1]}"


def resolve_run_path(run_dir: Path, value: str) -> Path:
    path = Path(value).expanduser()
    return path.resolve() if path.is_absolute() else (run_dir / path).resolve()


def compact_verification(record: dict[str, object]) -> dict[str, object]:
    return {
        key: record[key]
        for key in ("id", "task", "result", "check", "observation")
        if key in record
    }


def is_regular_file(path: Path, *, nonempty: bool = False) -> bool:
    try:
        return path.is_file() and (not nonempty or path.stat().st_size > 0)
    except OSError:
        return False


def check_declared_file(
    run_dir: Path, record: dict[str, object], field: str, issues: list[str]
) -> Path | None:
    if field not in record:
        return None
    value = record.get(field)
    if not isinstance(value, str) or not value:
        issues.append(f"{record_line(record)}: {field} must name a file")
        return None
    path = resolve_run_path(run_dir, value)
    if not is_regular_file(path):
        issues.append(f"{record_line(record)}: referenced {field} file does not exist: {value}")
        return None
    return path


def validate_run(run_dir: Path) -> dict[str, object]:
    run_dir = run_dir.expanduser().resolve()
    records, issues = read_ledger(run_dir / "ledger.jsonl")
    warnings: list[str] = []
    non_passing: list[dict[str, object]] = []

    known_records: list[dict[str, object]] = []
    for record in records:
        kind = record.get("type")
        if not isinstance(kind, str) or kind not in LEDGER_EVENT_TYPES:
            issues.append(f"{record_line(record)}: unknown ledger event type: {kind!r}")
        else:
            known_records.append(record)

    starts = [record for record in known_records if record.get("type") == "run_started"]
    closures = [record for record in known_records if record.get("type") == "run_closed"]
    if len(starts) != 1:
        issues.append(f"ledger must contain exactly one run_started record; found {len(starts)}")
    elif records and records[0] is not starts[0]:
        issues.append("run_started must be the first ledger record")
    if len(closures) > 1:
        issues.append(f"ledger may contain at most one run_closed record; found {len(closures)}")
    if closures and records and records[-1] is not closures[-1]:
        issues.append("run_closed must be the final ledger record")
    for closure in closures:
        if closure.get("judgment") not in {"passed", "blocked"}:
            issues.append(f"{record_line(closure)}: run_closed judgment must be passed or blocked")

    tasks: dict[str, dict[str, object]] = {}
    executions: dict[tuple[str, str], dict[str, object]] = {}
    execution_results: dict[tuple[str, str], dict[str, object]] = {}

    for record in known_records:
        kind = record.get("type")
        if kind == "task":
            task_id = record.get("id")
            if isinstance(task_id, str) and task_id:
                tasks[task_id] = record
            else:
                issues.append(f"{record_line(record)}: task must have a non-empty id")
        elif kind == "execution":
            key = execution_key(record)
            if key is None:
                issues.append(f"{record_line(record)}: execution must identify agent and execution")
            elif key in executions:
                issues.append(
                    f"{record_line(record)}: duplicate execution {display_execution(key)}"
                )
            else:
                executions[key] = record
            check_declared_file(run_dir, record, "prompt", issues)
            check_declared_file(run_dir, record, "events", issues)
        elif kind == "execution_result":
            status = record.get("status")
            if status not in TERMINAL_EXECUTION_STATUSES:
                issues.append(
                    f"{record_line(record)}: execution_result status is not terminal: {status}"
                )
            key = execution_key(record)
            if key is None:
                issues.append(
                    f"{record_line(record)}: execution_result must identify agent and execution"
                )
            elif key in execution_results:
                issues.append(
                    f"{record_line(record)}: duplicate execution_result for "
                    f"{display_execution(key)}"
                )
            else:
                execution_results[key] = record
        elif kind == "verification":
            result = record.get("result")
            if result not in VERIFICATION_RESULTS:
                issues.append(
                    f"{record_line(record)}: verification result is not recognized: {result}"
                )
            elif result != "passed":
                non_passing.append(compact_verification(record))
            evidence = record.get("evidence", [])
            if not isinstance(evidence, list) or not all(
                isinstance(item, str) and item for item in evidence
            ):
                issues.append(f"{record_line(record)}: evidence must be a list of file paths")
            else:
                for value in evidence:
                    check_declared_file(run_dir, {**record, "evidence": value}, "evidence", issues)

    for task_id, task in tasks.items():
        status = task.get("status")
        if status not in TERMINAL_TASK_STATUSES:
            issues.append(f"task {task_id} is not terminal; latest status is {status!r}")

    for key, execution in executions.items():
        result = execution_results.get(key)
        if result is None:
            issues.append(f"execution {display_execution(key)} has no terminal execution_result")
            continue
        task_id = execution.get("task")
        result_task = result.get("task")
        if isinstance(task_id, str) and isinstance(result_task, str) and result_task != task_id:
            issues.append(
                f"{record_line(result)}: execution_result task {result_task!r} "
                f"does not match execution task {task_id!r}"
            )
        if int(execution.get("_line", 0)) >= int(result.get("_line", 0)):
            issues.append(
                f"{record_line(result)}: execution {display_execution(key)} "
                "must be recorded before execution_result"
            )
        handoff_values = [
            source.get("handoff")
            for source in (execution, result)
            if "handoff" in source
        ]
        handoff_ok = bool(handoff_values) and all(
            isinstance(value, str)
            and bool(value)
            and is_regular_file(resolve_run_path(run_dir, value), nonempty=True)
            for value in handoff_values
        )
        if not handoff_ok:
            message = f"execution {display_execution(key)} handoff is missing or empty"
            (issues if result.get("status") == "complete" else warnings).append(message)

    for key, result in execution_results.items():
        if key not in executions:
            issues.append(
                f"{record_line(result)}: execution_result references unknown execution "
                f"{display_execution(key)}"
            )
    return {
        "ok": not issues,
        "issues": issues,
        "warnings": warnings,
        "non_passing_verifications": non_passing,
    }


def command_validate(args: argparse.Namespace) -> int:
    payload = validate_run(Path(args.run_dir))
    print(json.dumps(payload, indent=None if args.json else 2, sort_keys=True))
    return 0 if payload["ok"] else 1


def ledger_is_active(run_dir: Path) -> bool:
    records, issues = read_ledger(run_dir / "ledger.jsonl")
    if issues:
        return False
    kinds = [record.get("type") for record in records]
    return (
        bool(kinds)
        and all(kind in LEDGER_EVENT_TYPES for kind in kinds)
        and kinds[0] == "run_started"
        and kinds.count("run_started") == 1
        and "run_closed" not in kinds
    )


def ledger_lifecycle_parses(run_dir: Path) -> bool:
    records, issues = read_ledger(run_dir / "ledger.jsonl")
    if issues:
        return False
    kinds = [record.get("type") for record in records]
    if (
        not kinds
        or not all(kind in LEDGER_EVENT_TYPES for kind in kinds)
        or kinds.count("run_started") != 1
        or kinds[0] != "run_started"
    ):
        return False
    return kinds.count("run_closed") <= 1 and (
        "run_closed" not in kinds or kinds[-1] == "run_closed"
    )


def new_layout_event_paths(run_dir: Path) -> list[Path]:
    return sorted(
        (
            path
            for path in (run_dir / "agents").glob("*/execution-*/events.jsonl")
            if path.is_file()
        ),
        key=lambda path: (path.stat().st_mtime, str(path)),
        reverse=True,
    )


def source_for_path(path: Path, declared: object = None) -> str:
    if declared in {"exec", "ide"}:
        return str(declared)
    if not path.exists():
        return "exec"
    sample_lines, _, _ = read_lines(path, "ide")
    return source_from_events(list(iter_json_events(sample_lines)))


def inflight_targets(run_dir: Path) -> tuple[list[MonitorTarget], list[str]]:
    records, issues = read_ledger(run_dir / "ledger.jsonl")
    if issues:
        fallback = [
            MonitorTarget(path, source_for_path(path)) for path in new_layout_event_paths(run_dir)
        ]
        warning = (
            "ledger lifecycle could not be read; using low-confidence "
            "agents/*/execution-*/events.jsonl discovery"
        )
        return fallback, [warning, *issues]

    completed = {
        key
        for record in records
        if record.get("type") == "execution_result"
        for key in [execution_key(record)]
        if key is not None and record.get("status") in TERMINAL_EXECUTION_STATUSES
    }
    targets: list[MonitorTarget] = []
    for record in records:
        if record.get("type") != "execution":
            continue
        key = execution_key(record)
        if key is None or key in completed:
            continue
        value = record.get("events")
        if not isinstance(value, str) or not value:
            continue
        path = resolve_run_path(run_dir, value)
        targets.append(
            MonitorTarget(
                path=path,
                source=source_for_path(path, record.get("event_source")),
                agent=key[0],
                execution=key[1],
            )
        )
    return targets, []


def run_activity_mtime(run_dir: Path) -> float:
    targets, _ = inflight_targets(run_dir)
    mtimes = [target.path.stat().st_mtime for target in targets if target.path.exists()]
    if mtimes:
        return max(mtimes)
    try:
        return (run_dir / "ledger.jsonl").stat().st_mtime
    except OSError:
        return 0.0


def auto_discover_run_dir(repo: Path) -> tuple[Path | None, list[str]]:
    runs_dir = repo / ".codex-orchestrator" / "runs"
    if not runs_dir.exists():
        return None, []
    active = [
        run_dir for run_dir in runs_dir.iterdir() if run_dir.is_dir() and ledger_is_active(run_dir)
    ]
    if active:
        return max(active, key=lambda path: (run_activity_mtime(path), path.name)), []
    fallback = [
        run_dir
        for run_dir in runs_dir.iterdir()
        if run_dir.is_dir()
        and not ledger_lifecycle_parses(run_dir)
        and new_layout_event_paths(run_dir)
    ]
    if not fallback:
        return None, []
    selected = max(fallback, key=lambda path: (run_activity_mtime(path), path.name))
    return selected, [
        "no valid active ledger found; selected a run by low-confidence new-layout event mtime"
    ]


def monitor_run_dir(args: argparse.Namespace) -> tuple[Path | None, list[str]]:
    if args.run_id:
        return (
            Path(args.repo).expanduser() / ".codex-orchestrator" / "runs" / args.run_id,
            [],
        )
    if args.run_dir:
        return Path(args.run_dir).expanduser(), []
    return auto_discover_run_dir(Path(args.repo).expanduser())


def explicit_monitor_targets(args: argparse.Namespace) -> list[MonitorTarget]:
    return [
        MonitorTarget(
            path=Path(value).expanduser(),
            source=source_for_path(Path(value).expanduser(), args.source),
        )
        for value in (args.log or [])
    ]


def resolve_monitor_targets(args: argparse.Namespace) -> tuple[list[MonitorTarget], list[str]]:
    if args.log:
        return explicit_monitor_targets(args), []
    run_dir, warnings = monitor_run_dir(args)
    if run_dir is None:
        return [], warnings
    targets, target_warnings = inflight_targets(run_dir)
    return targets, [*warnings, *target_warnings]


def read_jsonl_delta(
    path: Path, offset: int, source: str
) -> tuple[list[dict[str, object]], int, int]:
    size = path.stat().st_size
    start = 0 if offset > size else max(0, offset)
    truncated_initial_tail = False
    if source == "ide" and offset == 0 and size > TAIL_LIMIT_BYTES:
        start = size - TAIL_LIMIT_BYTES
        truncated_initial_tail = True
    events: list[dict[str, object]] = []
    parse_errors = 0
    end = start
    with path.open("r", encoding="utf-8") as handle:
        handle.seek(start)
        if truncated_initial_tail:
            handle.readline()
        while True:
            line_start = handle.tell()
            line = handle.readline()
            if line == "":
                break
            if not line.endswith("\n"):
                end = line_start
                break
            end = handle.tell()
            stripped = line.strip()
            if not stripped:
                continue
            try:
                value = json.loads(stripped)
            except json.JSONDecodeError:
                parse_errors += 1
                continue
            if isinstance(value, dict):
                events.append(value)
            else:
                parse_errors += 1
    return events, end, parse_errors


def thread_id_from(event: dict[str, object], fallback: str) -> str:
    value = event.get("thread_id")
    if isinstance(value, str) and value:
        return value
    payload = event.get("payload")
    if isinstance(payload, dict):
        value = payload.get("thread_id")
        if isinstance(value, str) and value:
            return value
    return fallback


def monitor_payload(
    kind: str,
    target: MonitorTarget,
    event: dict[str, object] | None,
    offset: int,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "type": kind,
        "path": str(target.path),
        "source": target.source,
        "thread_id": thread_id_from(event or {}, target.path.stem),
        "offset": offset,
        "mtime": int(target.path.stat().st_mtime),
    }
    if target.agent:
        payload["agent"] = target.agent
    if target.execution:
        payload["execution"] = target.execution
    if event is not None and isinstance(event.get("turn_id"), str):
        payload["turn_id"] = event["turn_id"]
    return payload


def exec_terminal_notification(
    target: MonitorTarget, event: dict[str, object], offset: int
) -> dict[str, object] | None:
    kind = event_type(event)
    if kind == "turn.completed":
        payload = monitor_payload("codex_session_complete", target, event, offset)
        if "usage" in event:
            payload["usage"] = event["usage"]
        return payload
    if kind == "turn.failed":
        payload = monitor_payload("codex_session_failed", target, event, offset)
        if "error" in event:
            payload["error"] = event["error"]
        return payload
    record = EventRecord(event, kind)
    if kind == "error" and not is_reconnect_notice(record):
        payload = monitor_payload("codex_session_failed", target, event, offset)
        payload["message"] = event_text(event)
        return payload
    return None


def ide_terminal_notification(
    target: MonitorTarget, events: list[dict[str, object]], offset: int
) -> dict[str, object] | None:
    latest: tuple[int, str, dict[str, object], str | None] | None = None
    for index, event in enumerate(events):
        kind = event_type(event)
        text = event_text(event)
        if any(hint in text for hint in FAILURE_HINTS):
            latest = index, "failure", event, text
        if kind == "thread_goal_updated":
            payload_value = event.get("payload")
            payload_dict = payload_value if isinstance(payload_value, dict) else event
            goal = payload_dict.get("goal") if isinstance(payload_dict, dict) else None
            status = goal.get("status") if isinstance(goal, dict) else None
            if isinstance(status, str):
                latest = index, "goal", event, status.lower()

    if latest is None:
        return None
    _, kind, event, detail = latest
    if kind == "failure":
        payload = monitor_payload("codex_session_failed", target, event, offset)
        payload["message"] = detail
        return payload
    if detail in {"complete", "completed", "done"}:
        return monitor_payload("codex_session_complete", target, event, offset)
    if detail in {"failed", "error"}:
        return monitor_payload("codex_session_failed", target, event, offset)
    return None


def emit_monitor(payload: dict[str, object]) -> None:
    print(json_dumps(payload), flush=True)


def scan_monitor_target(
    target: MonitorTarget, state: dict[str, object], stale_seconds: int
) -> tuple[bool, bool, bool]:
    path = target.path
    if not path.exists() or not path.is_file():
        return False, False, False
    events, next_offset, parse_errors = read_jsonl_delta(
        path, int(state.get("offset", 0)), target.source
    )
    state["offset"] = next_offset
    terminal = False
    failed = False
    notifications: list[dict[str, object]] = []
    if target.source == "exec":
        notifications.extend(
            notification
            for event in events
            for notification in [exec_terminal_notification(target, event, next_offset)]
            if notification is not None
        )
    else:
        notification = ide_terminal_notification(target, events, next_offset)
        if notification is not None:
            notifications.append(notification)
    for notification in notifications:
        if parse_errors:
            notification["parse_errors"] = parse_errors
        emit_monitor(notification)
        terminal = True
        failed = notification["type"] == "codex_session_failed"
        state["status"] = "failed" if failed else "complete"

    stale = False
    idle_seconds = int(time.time() - path.stat().st_mtime)
    stale_marker = f"{path.stat().st_mtime_ns}:{next_offset}"
    if not terminal and stale_seconds >= 0 and idle_seconds >= stale_seconds:
        if state.get("stale_marker") != stale_marker:
            payload = monitor_payload("codex_session_stale", target, None, next_offset)
            payload["idle_seconds"] = idle_seconds
            if parse_errors:
                payload["parse_errors"] = parse_errors
            emit_monitor(payload)
            state["stale_marker"] = stale_marker
            state["status"] = "stale"
            stale = True
    return terminal, failed, stale


def command_monitor(args: argparse.Namespace) -> int:
    states: dict[Path, dict[str, object]] = {}
    emitted_warnings: set[str] = set()
    while True:
        targets, warnings = resolve_monitor_targets(args)
        for warning in warnings:
            if warning not in emitted_warnings:
                emit_monitor({"type": "monitor_warning", "message": warning})
                emitted_warnings.add(warning)
        any_failed = any(bool(state.get("failed")) for state in states.values())
        watched_done = bool(targets)
        for target in targets:
            state = states.setdefault(target.path, {"offset": 0, "status": "unknown"})
            if state.get("done"):
                continue
            terminal, failed, stale = scan_monitor_target(target, state, args.stale_seconds)
            if terminal or stale:
                state["done"] = True
                state["failed"] = failed
            if failed:
                any_failed = True
            if not state.get("done"):
                watched_done = False
        if args.once:
            return 1 if any_failed and args.fail_on_session_failure else 0
        if targets and watched_done:
            return 1 if any_failed and args.fail_on_session_failure else 0
        time.sleep(max(0.1, args.poll_interval))


def add_common_flags(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--source", choices=("exec", "ide"), help="Event source type.")
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")
    parser.add_argument("--dump-event-types", action="store_true", help="Print recent event types.")
    parser.add_argument("--file", help="Explicit event stream or rollout JSONL path.")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Parse headless Codex streams or IDE rollout JSONL."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    find_parser = subparsers.add_parser("find", help="Find the newest rollout for a thread id.")
    find_parser.add_argument("thread_id")
    find_parser.add_argument("--source", choices=("exec", "ide"), help="Event source type.")
    find_parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")
    find_parser.add_argument(
        "--dump-event-types", action="store_true", help="Print recent event types."
    )
    find_parser.add_argument("--file", help="Return this explicit path if supplied.")
    find_parser.set_defaults(func=command_find)

    state_parser = subparsers.add_parser("state", help="Classify a Codex session state.")
    state_parser.add_argument("thread_id")
    add_common_flags(state_parser)
    state_parser.set_defaults(func=command_state)

    tail_parser = subparsers.add_parser("tail", help="Read new events after an offset.")
    tail_parser.add_argument("thread_id")
    tail_parser.add_argument("--since-offset", required=True, type=int)
    add_common_flags(tail_parser)
    tail_parser.set_defaults(func=command_tail)

    monitor_parser = subparsers.add_parser(
        "monitor", help="Watch in-flight agent event streams from the prompt-first run layout."
    )
    monitor_parser.add_argument("run_dir", nargs="?", help="Run directory containing ledger.jsonl.")
    monitor_parser.add_argument("--run-id", help="Run id under .codex-orchestrator/runs.")
    monitor_parser.add_argument("--repo", default=".", help="Repository root used for discovery.")
    monitor_parser.add_argument(
        "--log",
        "--file",
        action="append",
        dest="log",
        help="Explicit event stream path. Repeatable.",
    )
    monitor_parser.add_argument(
        "--source", choices=("exec", "ide"), help="Source for explicit event streams."
    )
    monitor_parser.add_argument("--once", action="store_true", help="Scan once and exit.")
    monitor_parser.add_argument(
        "--stale-seconds", type=int, default=600, help="Emit stale after this many idle seconds."
    )
    monitor_parser.add_argument(
        "--poll-interval", type=float, default=30.0, help="Seconds between watch scans."
    )
    monitor_parser.add_argument(
        "--fail-on-session-failure",
        action="store_true",
        help="Exit nonzero when a watched session fails.",
    )
    monitor_parser.set_defaults(func=command_monitor)

    validate_parser = subparsers.add_parser(
        "validate", help="Check prompt-first run structure without making acceptance judgments."
    )
    validate_parser.add_argument("run_dir", help="Run directory containing ledger.jsonl.")
    validate_parser.add_argument("--json", action="store_true", help="Emit compact JSON.")
    validate_parser.set_defaults(func=command_validate)

    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    return args.func(args)
