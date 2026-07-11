from __future__ import annotations

import argparse
import time
from dataclasses import dataclass
from pathlib import Path

from .events import (
    StreamSummary,
    compatibility,
    event_text,
    json_dumps,
    summarize_stream,
)
from .journal import (
    TERMINAL_EXECUTION_STATUSES,
    execution_key,
    read_journal,
    resolve_run_path,
)


@dataclass(frozen=True)
class MonitorTarget:
    path: Path
    agent: str | None = None
    execution: str | None = None


def error_payload(message: str, *, path: Path | None = None) -> dict[str, object]:
    payload: dict[str, object] = {"type": "monitor_error", "message": message}
    if path is not None:
        payload["path"] = str(path)
    return payload


def inflight_targets(
    run_dir: Path,
) -> tuple[list[MonitorTarget], list[dict[str, object]]]:
    if not run_dir.is_dir():
        return [], [
            error_payload(
                "run directory does not exist or is not a directory", path=run_dir
            )
        ]

    records, issues = read_journal(
        run_dir / "journal.jsonl", allow_partial_final_line=True
    )
    if issues:
        return [], [
            error_payload(
                f"could not read run journal: {'; '.join(issues)}",
                path=run_dir / "journal.jsonl",
            )
        ]

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
    errors: list[dict[str, object]] = []
    for record in records:
        if record.get("type") != "execution":
            continue
        key = execution_key(record)
        if key is None:
            errors.append(error_payload("execution entry is missing agent or execution"))
            continue
        if key in completed:
            continue
        if record.get("event_source") == "claude":
            continue
        value = record.get("events")
        if not isinstance(value, str) or not value:
            errors.append(
                error_payload(
                    f"execution {key[0]}/{key[1]} has no events file"
                )
            )
            continue
        if record.get("event_source") not in {None, "exec"}:
            errors.append(
                error_payload(
                    f"execution {key[0]}/{key[1]} uses unsupported event source; "
                    "only managed exec streams are supported"
                )
            )
            continue
        try:
            path = resolve_run_path(run_dir, value)
        except (OSError, RuntimeError, ValueError) as exc:
            errors.append(
                error_payload(
                    f"execution {key[0]}/{key[1]} has an invalid events path: {exc}"
                )
            )
            continue
        targets.append(MonitorTarget(path=path, agent=key[0], execution=key[1]))
    return targets, errors


def resolve_monitor_targets(
    args: argparse.Namespace,
) -> tuple[list[MonitorTarget], list[dict[str, object]]]:
    selectors = bool(args.log) + bool(args.run_id or args.repo)
    if selectors != 1:
        return [], [
            error_payload(
                "provide exactly one target: --repo with --run-id or one or more --log paths"
            )
        ]

    if args.log:
        return [MonitorTarget(Path(value).expanduser()) for value in args.log], []
    if bool(args.run_id) != bool(args.repo):
        return [], [error_payload("--repo and --run-id must be provided together")]
    if args.run_id:
        run_dir = (
            Path(args.repo).expanduser()
            / ".codex-orchestrator"
            / "runs"
            / args.run_id
        )
    return inflight_targets(run_dir)


def thread_id_from(summary: StreamSummary, event: dict[str, object] | None) -> str:
    if summary.thread_id:
        return summary.thread_id
    if event is not None:
        value = event.get("thread_id")
        if isinstance(value, str) and value:
            return value
    return "unknown"


def monitor_payload(
    kind: str,
    target: MonitorTarget,
    summary: StreamSummary,
    event: dict[str, object] | None,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "type": kind,
        "path": str(target.path),
        "source": "exec",
        "thread_id": thread_id_from(summary, event),
        "mtime": int(target.path.stat().st_mtime),
    }
    if target.agent:
        payload["agent"] = target.agent
    if target.execution:
        payload["execution"] = target.execution
    return payload


def terminal_notification(
    target: MonitorTarget,
    summary: StreamSummary,
) -> dict[str, object] | None:
    notification_types = {
        "complete": "codex_agent_complete",
        "failed": "codex_agent_failed",
    }
    terminal = summary.terminal
    if terminal is None or summary.status not in notification_types:
        return None
    payload = monitor_payload(
        notification_types[summary.status], target, summary, terminal.event
    )
    if summary.status == "complete" and summary.usage is not None:
        payload["usage"] = summary.usage
    elif summary.status == "failed":
        if terminal.event_type == "turn.failed" and "error" in terminal.event:
            payload["error"] = terminal.event["error"]
        elif terminal.event_type == "error":
            payload["message"] = event_text(terminal.event)
    return payload


def emit_monitor(payload: dict[str, object]) -> None:
    print(json_dumps(payload), flush=True)


def scan_monitor_target(target: MonitorTarget, stale_seconds: int) -> str:
    path = target.path
    try:
        if not path.is_file():
            emit_monitor(
                error_payload("event stream does not exist or is not a file", path=path)
            )
            return "error"
        summary = summarize_stream(path)
        compat = compatibility(summary)
        if compat["parse_confidence"] == "low":
            payload = monitor_payload("codex_agent_unknown", target, summary, None)
            payload["compatibility"] = compat
            if summary.parse_errors:
                payload["parse_errors"] = summary.parse_errors
            emit_monitor(payload)
            return "unknown"

        notification = terminal_notification(target, summary)
        if notification is not None:
            if summary.parse_errors:
                notification["parse_errors"] = summary.parse_errors
            emit_monitor(notification)
            return summary.status

        idle_seconds = int(time.time() - path.stat().st_mtime)
        if stale_seconds >= 0 and idle_seconds >= stale_seconds:
            payload = monitor_payload("codex_agent_stale", target, summary, None)
            payload["idle_seconds"] = idle_seconds
            if summary.parse_errors:
                payload["parse_errors"] = summary.parse_errors
            emit_monitor(payload)
            return "stale"
    except (OSError, RuntimeError, ValueError) as exc:
        emit_monitor(error_payload(f"could not read event stream: {exc}", path=path))
        return "error"
    return "active"


def command_monitor(args: argparse.Namespace) -> int:
    done: set[MonitorTarget] = set()
    failed_seen = False
    unknown_seen = False
    while True:
        targets, errors = resolve_monitor_targets(args)
        if errors:
            for error in errors:
                emit_monitor(error)
            return 1
        if not targets:
            return 0

        pending = [target for target in targets if target not in done]
        for target in pending:
            outcome = scan_monitor_target(target, args.stale_seconds)
            if outcome != "active":
                done.add(target)
            failed_seen = failed_seen or outcome == "failed"
            unknown_seen = unknown_seen or outcome == "unknown"
            if outcome == "error":
                return 1

        if args.once:
            if unknown_seen:
                return 2
            return 1 if failed_seen and args.fail_on_agent_failure else 0
        if targets and all(target in done for target in targets):
            if unknown_seen:
                return 2
            return 1 if failed_seen and args.fail_on_agent_failure else 0
        time.sleep(max(0.1, args.poll_interval))
