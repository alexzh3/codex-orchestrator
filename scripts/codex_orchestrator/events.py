from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

PARSER_VERSION = "0.1.0"

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


@dataclass(frozen=True)
class EventRecord:
    event: dict[str, object]
    event_type: str


@dataclass
class StreamSummary:
    status: str = "idle"
    event_counts: Counter[str] = field(default_factory=Counter)
    known_count: int = 0
    parse_errors: int = 0
    unknown_event_types: set[str] = field(default_factory=set)
    thread_id: str | None = None
    usage: object = None
    error: object = None
    last_agent_message: str = ""
    terminal: EventRecord | None = None

    @property
    def event_count(self) -> int:
        return self.event_counts.total()

    def consume(self, record: EventRecord) -> None:
        kind = record.event_type
        self.event_counts[kind] += 1
        if kind in {"<invalid-json>", "<non-object>"}:
            self.parse_errors += 1
        if kind in EXEC_EVENT_TYPES or is_reconnect_notice(record):
            self.known_count += 1
        else:
            self.unknown_event_types.add(kind)
        if self.status == "idle" and (
            kind in EXEC_EVENT_TYPES or is_reconnect_notice(record)
        ):
            self.status = "starting"

        event = record.event
        if kind == "thread.started":
            native_id = event.get("thread_id")
            if isinstance(native_id, str) and native_id:
                self.thread_id = native_id
            self.status = "starting"
            self.usage = None
            self.error = None
            self.last_agent_message = ""
            self.terminal = None
        elif kind == "turn.started":
            self.status = "active"
            self.usage = None
            self.error = None
            self.terminal = None
        elif kind == "turn.completed":
            self.status = "complete"
            self.usage = event.get("usage")
            self.error = None
            self.terminal = record
        elif kind == "turn.failed":
            self.status = "failed"
            self.usage = None
            self.error = event.get("error")
            self.terminal = record
        elif kind == "error" and not is_reconnect_notice(record):
            self.status = "failed"
            self.usage = None
            self.error = event.get("error") or event.get("message")
            self.terminal = record
        elif kind == "item.completed":
            item = event.get("item")
            if isinstance(item, dict) and item.get("type") == "agent_message":
                text = item.get("text")
                if isinstance(text, str):
                    self.last_agent_message = text

    def details(self) -> dict[str, object]:
        details: dict[str, object] = {}
        if self.usage is not None:
            details["usage"] = self.usage
        if self.error is not None:
            details["error"] = self.error
        if self.thread_id is not None:
            details["thread_id"] = self.thread_id
        if self.last_agent_message:
            details["last_agent_message"] = self.last_agent_message
        return details


def json_dumps(payload: object) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def event_type(event: dict[str, object]) -> str:
    value = event.get("type")
    return value if isinstance(value, str) else "<missing>"


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


def is_reconnect_notice(record: EventRecord) -> bool:
    if record.event_type != "error":
        return False
    return "reconnecting" in json_dumps(record.event).lower()


def summarize_stream(path: Path) -> StreamSummary:
    summary = StreamSummary()
    with path.open("rb") as handle:
        while True:
            raw_line = handle.readline()
            if raw_line == b"":
                break
            terminated = raw_line.endswith(b"\n")
            try:
                line = raw_line.decode("utf-8")
            except UnicodeDecodeError:
                if not terminated:
                    if summary.status == "idle":
                        summary.status = "starting"
                    break
                summary.consume(
                    EventRecord({"_parse_error": "invalid UTF-8"}, "<invalid-json>")
                )
                continue
            record = decode_event_line(line)
            if record is None:
                continue
            if not terminated and record.event_type == "<invalid-json>":
                if summary.status == "idle":
                    summary.status = "starting"
                break
            summary.consume(record)
    return summary


def compatibility(summary: StreamSummary) -> dict[str, object]:
    warnings = [] if summary.event_count else ["no events found"]
    unknown_count = summary.event_count - summary.known_count
    confidence = (
        "low"
        if summary.event_count and unknown_count > summary.known_count
        else "high"
    )
    return {
        "parser_version": PARSER_VERSION,
        "parse_confidence": confidence,
        "unknown_event_types": sorted(summary.unknown_event_types),
        "warnings": warnings,
    }


def incompatible_message() -> str:
    return (
        f"ERROR: Codex exec JSONL appears incompatible (parser {PARSER_VERSION}). "
        "Run state --dump-event-types and update the parser. Do not infer agent status."
    )


def event_text(event: dict[str, object]) -> str:
    for key in ("message", "text", "error"):
        value = event.get(key)
        if isinstance(value, str):
            return value
    return json_dumps(event)
