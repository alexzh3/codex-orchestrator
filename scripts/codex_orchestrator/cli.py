#!/usr/bin/env python3
"""Command-line interface for run validation and Codex session inspection."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

from .events import (
    PARSER_VERSION,
    classify_exec,
    classify_ide,
    compatibility,
    find_rollout,
    incompatible_message,
    json_dumps,
    load_records,
    read_stream,
    source_for_path,
)
from .journal import validate_run
from .monitor import command_monitor


def source_and_path(args: argparse.Namespace) -> tuple[str, Path | None, list[str]]:
    warnings: list[str] = []
    explicit_path = Path(args.file).expanduser() if args.file else None
    path = explicit_path
    if path is None:
        path = find_rollout(args.thread_id)
        if path is None:
            warnings.append("no event source found; provide --file or check the thread id")
    declared = args.source or ("ide" if explicit_path is None and path is not None else None)
    source = source_for_path(path, declared)
    return source, path, warnings


def command_find(args: argparse.Namespace) -> int:
    path = find_rollout(args.thread_id)
    if args.json:
        print(
            json_dumps(
                {"thread_id": args.thread_id, "source": "ide", "path": str(path) if path else None}
            )
        )
    elif path:
        print(path)
    return 0 if path else 1


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
        status, details, _ = classify_exec(records)
    else:
        status, details, _ = classify_ide(records, path)

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

    lines, records, start, end, _ = read_stream(
        path, source, since_offset=args.since_offset
    )
    compat = compatibility(records, source)
    compat["warnings"] = [*compat["warnings"], *source_warnings]
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


def command_validate(args: argparse.Namespace) -> int:
    payload = validate_run(Path(args.run_dir))
    print(json.dumps(payload, indent=None if args.json else 2, sort_keys=True))
    return 0 if payload["ok"] else 1


def add_common_flags(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--source", choices=("exec", "ide"), help="Event source type.")
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")
    parser.add_argument("--file", help="Explicit event stream or rollout JSONL path.")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Parse headless Codex streams or IDE rollout JSONL."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    find_parser = subparsers.add_parser("find", help="Find the newest rollout for a thread id.")
    find_parser.add_argument("thread_id")
    find_parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")
    find_parser.set_defaults(func=command_find)

    state_parser = subparsers.add_parser("state", help="Classify a Codex session state.")
    state_parser.add_argument("thread_id")
    add_common_flags(state_parser)
    state_parser.add_argument(
        "--dump-event-types", action="store_true", help="Print recent event types."
    )
    state_parser.set_defaults(func=command_state)

    tail_parser = subparsers.add_parser("tail", help="Read new events after an offset.")
    tail_parser.add_argument("thread_id")
    tail_parser.add_argument("--since-offset", required=True, type=int)
    add_common_flags(tail_parser)
    tail_parser.set_defaults(func=command_tail)

    monitor_parser = subparsers.add_parser(
        "monitor", help="Watch in-flight agent event streams from the prompt-first run layout."
    )
    monitor_parser.add_argument(
        "run_dir", nargs="?", help="Run directory containing journal.jsonl."
    )
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
    validate_parser.add_argument("run_dir", help="Run directory containing journal.jsonl.")
    validate_parser.add_argument("--json", action="store_true", help="Emit compact JSON.")
    validate_parser.set_defaults(func=command_validate)

    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    return args.func(args)
