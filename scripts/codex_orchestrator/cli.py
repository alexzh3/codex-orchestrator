#!/usr/bin/env python3
"""Command-line interface for run validation and Codex agent inspection."""

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
from .role_config import (
    ROLES,
    RoleConfigError,
    initialize_role_config,
    load_role_config,
    role_config_path,
)
from .runner import command_run


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


def command_run_hint(_args: argparse.Namespace) -> int:
    print(f"usage: {Path(sys.argv[0]).name} run --help", file=sys.stderr)
    return 2


def command_config_init(args: argparse.Namespace) -> int:
    try:
        path = initialize_role_config(Path(args.repo))
    except RoleConfigError as exc:
        print(f"config init: {exc}", file=sys.stderr)
        return 1
    print(f"created {path}")
    return 0


def command_config_check(args: argparse.Namespace) -> int:
    try:
        config = load_role_config(Path(args.repo))
        path = config.path if config is not None else role_config_path(Path(args.repo))
    except RoleConfigError as exc:
        print(f"config check: {exc}", file=sys.stderr)
        return 1
    if config is None:
        print(f"configuration disabled: {path}")
    else:
        print(f"configuration valid: {path}")
    return 0


def command_config_show(args: argparse.Namespace) -> int:
    try:
        config = load_role_config(Path(args.repo))
        path = config.path if config is not None else role_config_path(Path(args.repo))
    except RoleConfigError as exc:
        print(f"config show: {exc}", file=sys.stderr)
        return 1

    payload: dict[str, object] = {
        "enabled": config is not None,
        "path": str(path),
        "role": args.role,
    }
    if config is not None:
        policy = config.policy_for(args.role)
        payload.update(
            {
                "model": policy.model,
                "reasoning_efforts": list(policy.reasoning_efforts),
                "service_tier": policy.speed,
                "speed": policy.speed,
            }
        )
    if args.json:
        print(json.dumps(payload, sort_keys=True))
    else:
        for key, value in payload.items():
            if isinstance(value, list):
                value = ", ".join(value)
            print(f"{key}: {value}")
    return 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Inspect managed Codex exec streams and validate orchestration runs."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    state_parser = subparsers.add_parser("state", help="Classify a Codex agent state.")
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
    monitor_parser.add_argument("--run-id", help="Run id under .codex-orchestrator/runs.")
    monitor_parser.add_argument("--repo", help="Repository root paired with --run-id.")
    monitor_parser.add_argument(
        "--log",
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
        "--fail-on-agent-failure",
        action="store_true",
        help="Exit nonzero when a watched agent fails.",
    )
    monitor_parser.set_defaults(func=command_monitor)

    validate_parser = subparsers.add_parser(
        "validate", help="Check prompt-first run structure without making acceptance judgments."
    )
    validate_parser.add_argument("run_dir", help="Run directory containing journal.jsonl.")
    validate_parser.set_defaults(func=command_validate)

    config_parser = subparsers.add_parser(
        "config", help="Initialize or inspect the opt-in role policy."
    )
    config_subparsers = config_parser.add_subparsers(dest="config_command", required=True)

    config_init_parser = config_subparsers.add_parser(
        "init", help="Create the default repository role policy."
    )
    config_init_parser.add_argument("--repo", required=True, help="Repository root.")
    config_init_parser.set_defaults(func=command_config_init)

    config_check_parser = config_subparsers.add_parser(
        "check", help="Validate the repository role policy when present."
    )
    config_check_parser.add_argument("--repo", required=True, help="Repository root.")
    config_check_parser.set_defaults(func=command_config_check)

    config_show_parser = config_subparsers.add_parser(
        "show", help="Show resolved settings for one role."
    )
    config_show_parser.add_argument("--repo", required=True, help="Repository root.")
    config_show_parser.add_argument("--role", required=True, choices=ROLES)
    config_show_parser.add_argument("--json", action="store_true")
    config_show_parser.set_defaults(func=command_config_show)

    run_parser = subparsers.add_parser(
        "run", help="Capture child events; see run --help."
    )
    run_parser.set_defaults(func=command_run_hint)

    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    effective_argv = sys.argv[1:] if argv is None else argv
    if effective_argv and effective_argv[0] == "run":
        return command_run(effective_argv[1:])
    args = parse_args(effective_argv)
    return args.func(args)
