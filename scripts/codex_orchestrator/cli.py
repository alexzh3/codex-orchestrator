#!/usr/bin/env python3
"""Command-line interface for run validation and Codex session inspection."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .events import (
    compatibility,
    incompatible_message,
    json_dumps,
    summarize_stream,
)
from .journal import validate_run
from .monitor import command_monitor


def command_state(args: argparse.Namespace) -> int:
    path = Path(args.file).expanduser() if args.file else None
    if path is None or not path.is_file():
        payload = {
            "type": "state_error",
            "thread_id": args.thread_id,
            "path": str(path) if path is not None else None,
            "message": "event stream does not exist or is not a file",
        }
        print(json_dumps(payload))
        return 1

    try:
        summary = summarize_stream(path)
    except (OSError, RuntimeError) as exc:
        print(
            json_dumps(
                {
                    "type": "state_error",
                    "thread_id": args.thread_id,
                    "path": str(path),
                    "message": f"could not read event stream: {exc}",
                }
            )
        )
        return 1
    compat = compatibility(summary)

    if args.dump_event_types:
        payload = {
            "thread_id": summary.thread_id or args.thread_id,
            "source": "exec",
            "path": str(path),
            "event_types": dict(sorted(summary.event_counts.items())),
            "compatibility": compat,
        }
        print(json_dumps(payload) if args.json else payload)
        return 2 if compat["parse_confidence"] == "low" else 0

    if compat["parse_confidence"] == "low":
        payload = {
            "thread_id": summary.thread_id or args.thread_id,
            "source": "exec",
            "path": str(path),
            "status": "unknown",
            "compatibility": compat,
        }
        print(json_dumps(payload) if args.json else payload)
        print(incompatible_message(), file=sys.stderr)
        return 2

    payload = {
        "thread_id": summary.thread_id or args.thread_id,
        "source": "exec",
        "path": str(path),
        "status": summary.status,
        "details": summary.details(),
        "compatibility": compat,
    }
    print(json_dumps(payload) if args.json else payload)
    return 0


def command_validate(args: argparse.Namespace) -> int:
    payload = validate_run(Path(args.run_dir))
    print(json.dumps(payload, sort_keys=True))
    return 0 if payload["ok"] else 1


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Inspect managed Codex exec streams and validate orchestration runs."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    state_parser = subparsers.add_parser("state", help="Classify a Codex session state.")
    state_parser.add_argument("thread_id")
    state_parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")
    state_parser.add_argument("--file", help="Managed Codex exec JSONL path.")
    state_parser.add_argument(
        "--dump-event-types", action="store_true", help="Print observed event types."
    )
    state_parser.set_defaults(func=command_state)

    monitor_parser = subparsers.add_parser(
        "monitor", help="Watch in-flight agent event streams from the prompt-first run layout."
    )
    monitor_parser.add_argument(
        "run_dir", nargs="?", help="Run directory containing journal.jsonl."
    )
    monitor_parser.add_argument("--run-id", help="Run id under .codex-orchestrator/runs.")
    monitor_parser.add_argument("--repo", help="Repository root paired with --run-id.")
    monitor_parser.add_argument(
        "--log",
        "--file",
        action="append",
        dest="log",
        help="Explicit managed exec stream path. Repeatable.",
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
    validate_parser.set_defaults(func=command_validate)

    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    return args.func(args)
