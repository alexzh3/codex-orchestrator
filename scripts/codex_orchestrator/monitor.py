from __future__ import annotations

import argparse
import time
from dataclasses import dataclass
from pathlib import Path

from .events import (
    FAILURE_HINTS,
    EventRecord,
    classify_exec,
    classify_ide,
    compatibility,
    event_text,
    json_dumps,
    read_stream,
    source_for_path,
)
from .journal import (
    TERMINAL_EXECUTION_STATUSES,
    execution_key,
    journal_lifecycle,
    read_journal,
    resolve_run_path,
)


@dataclass(frozen=True)
class MonitorTarget:
    path: Path
    source: str
    agent: str | None = None
    execution: str | None = None


def execution_event_paths(run_dir: Path) -> list[Path]:
    return sorted(
        (
            path
            for path in run_dir.glob("*/execution-*/events.jsonl")
            if path.is_file()
        ),
        key=lambda path: (path.stat().st_mtime, str(path)),
        reverse=True,
    )


def inflight_targets(run_dir: Path) -> tuple[list[MonitorTarget], list[str]]:
    records, issues = read_journal(run_dir / "journal.jsonl")
    if issues:
        fallback = [
            MonitorTarget(path, source_for_path(path)) for path in execution_event_paths(run_dir)
        ]
        warning = (
            "journal lifecycle could not be read; using low-confidence "
            "*/execution-*/events.jsonl discovery"
        )
        return fallback, [warning, *issues]

    completed = {
        key
        for record in records
        if record.get("type") == "execution_result"
        for key in [execution_key(record)]
        if key is not None
        and isinstance(record.get("status"), str)
        and record.get("status") in TERMINAL_EXECUTION_STATUSES
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
    mtimes = [target.path.stat().st_mtime for target in targets if target.path.is_file()]
    if mtimes:
        return max(mtimes)
    try:
        return (run_dir / "journal.jsonl").stat().st_mtime
    except OSError:
        return 0.0


def auto_discover_run_dir(repo: Path) -> tuple[Path | None, list[str]]:
    runs_dir = repo / ".codex-orchestrator" / "runs"
    if not runs_dir.exists():
        return None, []
    candidates = [
        (run_dir, journal_lifecycle(run_dir))
        for run_dir in runs_dir.iterdir()
        if run_dir.is_dir()
    ]
    active = [run_dir for run_dir, lifecycle in candidates if lifecycle == "active"]
    if active:
        return max(active, key=lambda path: (run_activity_mtime(path), path.name)), []
    fallback = [
        run_dir
        for run_dir, lifecycle in candidates
        if lifecycle == "invalid" and execution_event_paths(run_dir)
    ]
    if not fallback:
        return None, []
    selected = max(fallback, key=lambda path: (run_activity_mtime(path), path.name))
    return selected, [
        "no valid active journal found; selected a run by low-confidence execution event mtime"
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
) -> dict[str, object]:
    payload: dict[str, object] = {
        "type": kind,
        "path": str(target.path),
        "source": target.source,
        "thread_id": thread_id_from(event or {}, target.path.stem),
        "mtime": int(target.path.stat().st_mtime),
    }
    if target.agent:
        payload["agent"] = target.agent
    if target.execution:
        payload["execution"] = target.execution
    if event is not None and isinstance(event.get("turn_id"), str):
        payload["turn_id"] = event["turn_id"]
    return payload


def terminal_notification(
    target: MonitorTarget,
    status: str,
    details: dict[str, object],
    terminal: EventRecord | None,
) -> dict[str, object] | None:
    notification_types = {
        "complete": "codex_session_complete",
        "failed": "codex_session_failed",
        "awaiting-approval": "codex_session_blocked",
    }
    if terminal is None or status not in notification_types:
        return None
    payload = monitor_payload(notification_types[status], target, terminal.event)
    if status == "complete" and "usage" in details:
        payload["usage"] = details["usage"]
    elif status == "failed" and target.source == "exec":
        if terminal.event_type == "turn.failed" and "error" in terminal.event:
            payload["error"] = terminal.event["error"]
        elif terminal.event_type == "error":
            payload["message"] = event_text(terminal.event)
    elif status == "failed" and any(
        hint in event_text(terminal.event) for hint in FAILURE_HINTS
    ):
        payload["message"] = event_text(terminal.event)
    elif status == "awaiting-approval":
        for key in ("goal_status", "goal_text"):
            if key in details:
                payload[key] = details[key]
    return payload


def emit_monitor(payload: dict[str, object]) -> None:
    print(json_dumps(payload), flush=True)


def scan_monitor_target(
    target: MonitorTarget, state: dict[str, object], stale_seconds: int
) -> tuple[bool, bool, bool, bool]:
    path = target.path
    if not path.is_file():
        return False, False, False, False
    records, history_truncated, parse_errors = read_stream(
        path, target.source, include_unterminated=True
    )
    compat = compatibility(
        records,
        target.source,
        history_truncated=history_truncated,
    )
    if compat["parse_confidence"] == "low":
        marker = f"{path.stat().st_mtime_ns}:{','.join(compat['unknown_event_types'])}"
        if state.get("compatibility_marker") != marker:
            payload = monitor_payload("codex_session_unknown", target, None)
            payload["compatibility"] = compat
            if parse_errors:
                payload["parse_errors"] = parse_errors
            emit_monitor(payload)
            state["compatibility_marker"] = marker
        return False, False, False, True
    if target.source == "exec":
        status, details, terminal_event = classify_exec(records)
    else:
        status, details, terminal_event = classify_ide(records, path)
    notification = terminal_notification(target, status, details, terminal_event)
    terminal = notification is not None
    failed = status == "failed" and terminal
    if notification is not None:
        if parse_errors:
            notification["parse_errors"] = parse_errors
        emit_monitor(notification)

    stale = False
    idle_seconds = int(time.time() - path.stat().st_mtime)
    stale_marker = str(path.stat().st_mtime_ns)
    if not terminal and stale_seconds >= 0 and idle_seconds >= stale_seconds:
        if state.get("stale_marker") != stale_marker:
            payload = monitor_payload("codex_session_stale", target, None)
            payload["idle_seconds"] = idle_seconds
            if parse_errors:
                payload["parse_errors"] = parse_errors
            emit_monitor(payload)
            state["stale_marker"] = stale_marker
            stale = True
    return terminal, failed, stale, False


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
        any_unknown = any(bool(state.get("unknown")) for state in states.values())
        any_error = any(bool(state.get("error")) for state in states.values())
        watched_done = bool(targets)
        for target in targets:
            state = states.setdefault(target.path, {})
            if state.get("done"):
                continue
            if not target.path.is_file():
                emit_monitor(
                    {
                        "type": "monitor_error",
                        "path": str(target.path),
                        "message": "event stream does not exist or is not a file",
                    }
                )
                state["done"] = True
                state["error"] = True
                any_error = True
                continue
            terminal, failed, stale, unknown = scan_monitor_target(
                target, state, args.stale_seconds
            )
            if terminal or stale or unknown:
                state["done"] = True
                state["failed"] = failed
                state["unknown"] = unknown
            if failed:
                any_failed = True
            if unknown:
                any_unknown = True
            if not state.get("done"):
                watched_done = False
        if args.once:
            if any_error:
                return 1
            if any_unknown:
                return 2
            return 1 if any_failed and args.fail_on_session_failure else 0
        if targets and watched_done:
            if any_error:
                return 1
            if any_unknown:
                return 2
            return 1 if any_failed and args.fail_on_session_failure else 0
        time.sleep(max(0.1, args.poll_interval))
