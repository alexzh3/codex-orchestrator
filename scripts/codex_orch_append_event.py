#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Append one JSON object to a codex-orchestrator events.jsonl file."
    )
    parser.add_argument("run_dir", help="Run directory containing events.jsonl.")
    parser.add_argument(
        "event_json",
        nargs="?",
        help="JSON object to append. If omitted, stdin is read.",
    )
    parser.add_argument(
        "--event",
        dest="event_option",
        help="JSON object to append. Overrides the positional event.",
    )
    return parser.parse_args()


def load_event(raw: str) -> dict[str, object]:
    try:
        event = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"ERROR: event is not valid JSON: {exc}") from exc
    if not isinstance(event, dict):
        raise SystemExit("ERROR: event must be a JSON object")
    return event


def append_jsonl(path: Path, event: dict[str, object]) -> None:
    encoded = (
        json.dumps(event, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode("utf-8")
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
    try:
        written = os.write(fd, encoded)
        if written != len(encoded):
            raise OSError(f"short write to {path}: {written} of {len(encoded)} bytes")
        os.fsync(fd)
    finally:
        os.close(fd)


def main() -> int:
    args = parse_args()
    raw_event = args.event_option if args.event_option is not None else args.event_json
    if raw_event is None:
        raw_event = sys.stdin.read()
    raw_event = raw_event.strip()
    if not raw_event:
        raise SystemExit("ERROR: no event JSON provided")

    run_dir = Path(args.run_dir).expanduser()
    if not run_dir.exists() or not run_dir.is_dir():
        raise SystemExit(f"ERROR: run directory does not exist: {run_dir}")

    event = load_event(raw_event)
    events_path = run_dir / "events.jsonl"
    append_jsonl(events_path, event)
    print(events_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
