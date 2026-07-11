from __future__ import annotations

import json
import time
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

PARSER_VERSION = "0.1.0"
IDE_HISTORY_LIMIT_BYTES = 500_000

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


def decode_event_line(line: str) -> EventRecord | None:
    stripped = line.strip()
    if not stripped:
        return None
    try:
        event = json.loads(stripped)
    except json.JSONDecodeError:
        return EventRecord({"_parse_error": stripped[:200]}, "<invalid-json>")
    if not isinstance(event, dict):
        return EventRecord(
            {"_parse_error": "top-level JSON value is not an object"}, "<non-object>"
        )
    return EventRecord(event, event_type(event))


def read_stream(
    path: Path,
    source: str,
    *,
    include_unterminated: bool = False,
) -> tuple[list[EventRecord], bool, int]:
    size = path.stat().st_size
    history_truncated = source == "ide" and size > IDE_HISTORY_LIMIT_BYTES
    start = size - IDE_HISTORY_LIMIT_BYTES if history_truncated else 0
    records: list[EventRecord] = []
    parse_errors = 0

    with path.open("rb") as handle:
        handle.seek(start)
        if history_truncated and start > 0:
            handle.seek(start - 1)
            starts_on_boundary = handle.read(1) == b"\n"
            handle.seek(start)
            if not starts_on_boundary:
                handle.readline()
        while True:
            raw_line = handle.readline()
            if raw_line == b"":
                break
            terminated = raw_line.endswith(b"\n")
            if not terminated and not include_unterminated:
                break
            try:
                line = raw_line.decode("utf-8")
            except UnicodeDecodeError:
                if not terminated:
                    break
                records.append(
                    EventRecord({"_parse_error": "invalid UTF-8"}, "<invalid-json>")
                )
                parse_errors += 1
                continue
            record = decode_event_line(line)
            if record is None:
                continue
            if not terminated and record.event_type == "<invalid-json>":
                break
            records.append(record)
            if record.event_type in {"<invalid-json>", "<non-object>"}:
                parse_errors += 1
    return records, history_truncated, parse_errors


def known_types_for_source(source: str) -> set[str]:
    return EXEC_EVENT_TYPES if source == "exec" else IDE_EVENT_TYPES


def is_reconnect_notice(record: EventRecord) -> bool:
    if record.event_type != "error":
        return False
    return "reconnecting" in json_dumps(record.event).lower()


def compatibility(
    records: list[EventRecord], source: str, *, history_truncated: bool = False
) -> dict[str, object]:
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
    missing_ide_lifecycle = (
        source == "ide"
        and history_truncated
        and not any(record.event_type == "thread_goal_updated" for record in records)
    )
    if missing_ide_lifecycle:
        warnings.append("bounded IDE history contains no lifecycle event")
    parse_confidence = (
        "low" if (records and unknown_count > known_count) or missing_ide_lifecycle else "high"
    )
    return {
        "parser_version": PARSER_VERSION,
        "parse_confidence": parse_confidence,
        "unknown_event_types": unknown,
        "warnings": warnings,
    }


def incompatible_message() -> str:
    return (
        f"ERROR: Codex rollout/JSON format appears incompatible (parser {PARSER_VERSION}). "
        "Run state --dump-event-types and update the parser. Do not infer session status."
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
    exec_score = sum(counts[kind] for kind in EXEC_EVENT_TYPES)
    ide_score = sum(counts[kind] for kind in IDE_EVENT_TYPES)
    if exec_score > ide_score:
        return "exec"
    if ide_score > exec_score:
        return "ide"
    return "exec"


def source_for_path(path: Path | None, declared: object = None) -> str:
    if isinstance(declared, str) and declared in {"exec", "ide"}:
        return str(declared)
    if path is None or not path.is_file():
        return "exec"
    records, _, _ = read_stream(path, "ide")
    return source_from_events(records)


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


def classify_exec(
    records: list[EventRecord],
) -> tuple[str, dict[str, object], EventRecord | None]:
    status = "idle"
    usage: object = None
    error: object = None
    terminal: EventRecord | None = None
    last_agent_text = ""
    thread_started = False
    for record in records:
        if record.event_type == "thread.started":
            thread_started = True
            status = "idle"
            terminal = None
            usage = None
            error = None
        elif record.event_type == "turn.started":
            status = "active"
            terminal = None
            usage = None
            error = None
        elif record.event_type == "turn.completed":
            status = "complete"
            terminal = record
            usage = record.event.get("usage")
            error = None
        elif record.event_type == "turn.failed":
            status = "failed"
            terminal = record
            usage = None
            error = record.event.get("error")
        elif record.event_type == "error" and not is_reconnect_notice(record):
            status = "failed"
            terminal = record
            usage = None
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
    return status, details, terminal


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


def classify_ide(
    records: list[EventRecord], path: Path | None
) -> tuple[str, dict[str, object], EventRecord | None]:
    status = "idle"
    terminal: EventRecord | None = None
    goal_status: str | None = None
    goal_text: str | None = None
    last_agent_text = ""

    for record in records:
        text = event_text(record.event)
        if record.event_type == "agent_message" and any(
            hint in text for hint in FAILURE_HINTS
        ):
            status = "failed"
            terminal = record
        if record.event_type == "thread_goal_updated":
            payload = record.event.get("payload")
            payload_dict = payload if isinstance(payload, dict) else record.event
            goal = payload_dict.get("goal") if isinstance(payload_dict, dict) else None
            if isinstance(goal, dict):
                status_value = goal.get("status")
                text_value = goal.get("text")
                if status_value is not None:
                    goal_status = str(status_value)
                    status = goal_status_to_session_status(goal_status) or "idle"
                    terminal = (
                        record
                        if status in {"complete", "failed", "awaiting-approval"}
                        else None
                    )
                goal_text = str(text_value) if text_value is not None else goal_text
        elif record.event_type == "agent_message":
            last_agent_text = text

    details: dict[str, object] = {}
    if goal_status is not None:
        details["goal_status"] = goal_status
    if goal_text:
        details["goal_text"] = goal_text
    if last_agent_text:
        details["last_agent_message"] = last_agent_text
    if path is not None:
        details["idle_seconds"] = int(time.time() - path.stat().st_mtime)
    return status, details, terminal
