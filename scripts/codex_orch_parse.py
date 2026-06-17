#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


PARSER_VERSION = "0.1.0"
TAIL_LIMIT_BYTES = 500_000

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
            yield EventRecord({"_parse_error": "top-level JSON value is not an object"}, "<non-object>")
            continue
        yield EventRecord(event, event_type(event))


def read_lines(path: Path, source: str, *, since_offset: int | None = None) -> tuple[list[str], int, int]:
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
        1
        for record in records
        if record.event_type in known or is_reconnect_notice(record)
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
    matches = [
        path
        for path in sessions_root.rglob(f"*{thread_id}*")
        if path.is_file()
    ]
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
    details: dict[str, object] = {}
    if usage is not None:
        details["usage"] = usage
    if error is not None:
        details["error"] = error
    if thread_started:
        details["thread_started"] = True
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
    if status in {"active", "idle"} and any(hint in last_agent_text.lower() for hint in APPROVAL_HINTS):
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
        print(json_dumps({"thread_id": args.thread_id, "source": source, "path": str(path) if path else None}))
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


def add_common_flags(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--source", choices=("exec", "ide"), help="Event source type.")
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")
    parser.add_argument("--dump-event-types", action="store_true", help="Print recent event types.")
    parser.add_argument("--file", help="Explicit event stream or rollout JSONL path.")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Parse Codex exec streams or IDE rollout JSONL.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    find_parser = subparsers.add_parser("find", help="Find the newest rollout for a thread id.")
    find_parser.add_argument("thread_id")
    find_parser.add_argument("--source", choices=("exec", "ide"), help="Event source type.")
    find_parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")
    find_parser.add_argument("--dump-event-types", action="store_true", help="Print recent event types.")
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

    return parser.parse_args()


def main() -> int:
    args = parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
