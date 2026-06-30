#!/usr/bin/env python3
"""Best-effort Claude Code monitor for codex-orchestrator run logs.

Contract:
- stdout is the notification stream; every emitted line is compact JSON.
- Input is a run directory, --run-id resolved under --repo, or one or more --log paths.
- With no args, auto-discovers the newest active run under .codex-orchestrator/runs.
- In auto mode, keeps scanning for future logs when none exist yet unless --once is set.
- Watches the newest captured Codex JSONL log(s) and emits material events:
  codex_session_complete, codex_session_failed, codex_session_stale.
- With multiple watched logs, exits after all watched paths are complete, failed, or stale.
- With --fail-on-session-failure, exits nonzero after all watched paths are done if any failed.
- Does not mutate the ledger. With --once, it exits after one scan.
- Stdlib only; parsing follows scripts/codex_orch_parse.py's exec event conventions.
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any


TERMINAL_TYPES = {"turn.completed", "turn.failed"}


def compact_json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def event_type(event: dict[str, Any]) -> str:
    payload = event.get("payload")
    if isinstance(payload, dict) and isinstance(payload.get("type"), str):
        return str(payload["type"])
    if isinstance(event.get("type"), str):
        return str(event["type"])
    return "<missing>"


def event_text(event: dict[str, Any]) -> str:
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
    return compact_json(event)


def is_reconnect_notice(event: dict[str, Any]) -> bool:
    if event_type(event) != "error":
        return False
    return "reconnect" in compact_json(event).lower()


def run_dir_from_args(args: argparse.Namespace) -> Path | None:
    if args.run_id:
        return Path(args.repo).expanduser() / ".codex-orchestrator" / "runs" / args.run_id
    if args.run_dir:
        return Path(args.run_dir).expanduser()
    return auto_discover_run_dir(Path(args.repo).expanduser(), args.max_logs)


def run_status(run_dir: Path) -> str | None:
    state_path = run_dir / "state.json"
    if not state_path.exists():
        return None
    try:
        payload = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    status = payload.get("status")
    return status if isinstance(status, str) else None


def newest_log_mtime(run_dir: Path, max_logs: int) -> float | None:
    logs = newest_logs(run_dir, max_logs)
    if not logs:
        return None
    return max(path.stat().st_mtime for path in logs)


def auto_discover_run_dir(repo: Path, max_logs: int) -> Path | None:
    runs_dir = repo / ".codex-orchestrator" / "runs"
    if not runs_dir.exists():
        return None
    candidates: list[tuple[float, Path]] = []
    for run_dir in runs_dir.iterdir():
        if not run_dir.is_dir() or run_status(run_dir) != "active":
            continue
        mtime = newest_log_mtime(run_dir, max_logs)
        if mtime is not None:
            candidates.append((mtime, run_dir))
    if not candidates:
        return None
    candidates.sort(key=lambda item: (item[0], item[1].name), reverse=True)
    return candidates[0][1]


def newest_logs(run_dir: Path, max_logs: int) -> list[Path]:
    logs_dir = run_dir / "logs"
    if not logs_dir.exists():
        return []
    candidates = [path for path in logs_dir.glob("*.jsonl") if path.is_file()]
    candidates.sort(key=lambda path: (path.stat().st_mtime, path.name), reverse=True)
    return candidates[:max(1, max_logs)]


def resolve_logs(args: argparse.Namespace) -> list[Path]:
    if args.log:
        return [Path(value).expanduser() for value in args.log]
    run_dir = run_dir_from_args(args)
    if run_dir is None:
        return []
    return newest_logs(run_dir, args.max_logs)


def read_jsonl_delta(path: Path, offset: int) -> tuple[list[dict[str, Any]], int, int]:
    size = path.stat().st_size
    start = 0 if offset > size else max(0, offset)
    events: list[dict[str, Any]] = []
    parse_errors = 0
    end = start
    with path.open("r", encoding="utf-8") as handle:
        handle.seek(start)
        while True:
            line_start = handle.tell()
            line = handle.readline()
            if line == "":
                break
            if not line.endswith("\n"):
                end = line_start
                break
            line_end = handle.tell()
            stripped = line.strip()
            end = line_end
            if not stripped:
                continue
            try:
                event = json.loads(stripped)
            except json.JSONDecodeError:
                parse_errors += 1
                continue
            if isinstance(event, dict):
                events.append(event)
            else:
                parse_errors += 1
    return events, end, parse_errors


def thread_id_from(event: dict[str, Any], fallback: str) -> str:
    value = event.get("thread_id")
    if isinstance(value, str) and value:
        return value
    payload = event.get("payload")
    if isinstance(payload, dict):
        payload_value = payload.get("thread_id")
        if isinstance(payload_value, str) and payload_value:
            return payload_value
    return fallback


def turn_id_from(event: dict[str, Any]) -> str | None:
    value = event.get("turn_id")
    return value if isinstance(value, str) else None


def emit(payload: dict[str, Any]) -> None:
    print(compact_json(payload), flush=True)


def base_payload(kind: str, path: Path, event: dict[str, Any] | None, offset: int) -> dict[str, Any]:
    fallback = path.stem
    thread_id = thread_id_from(event or {}, fallback)
    payload: dict[str, Any] = {
        "type": kind,
        "path": str(path),
        "thread_id": thread_id,
        "offset": offset,
        "mtime": int(path.stat().st_mtime),
    }
    if event is not None:
        turn_id = turn_id_from(event)
        if turn_id is not None:
            payload["turn_id"] = turn_id
    return payload


def terminal_event(path: Path, event: dict[str, Any], offset: int) -> dict[str, Any] | None:
    kind = event_type(event)
    if kind == "turn.completed":
        payload = base_payload("codex_session_complete", path, event, offset)
        if "usage" in event:
            payload["usage"] = event["usage"]
        return payload
    if kind == "turn.failed":
        payload = base_payload("codex_session_failed", path, event, offset)
        if "error" in event:
            payload["error"] = event["error"]
        return payload
    if kind == "error" and not is_reconnect_notice(event):
        payload = base_payload("codex_session_failed", path, event, offset)
        payload["message"] = event_text(event)
        return payload
    return None


def scan_path(path: Path, state: dict[str, Any], stale_seconds: int) -> tuple[bool, bool, bool]:
    if not path.exists() or not path.is_file():
        return False, False, False

    events, next_offset, parse_errors = read_jsonl_delta(path, int(state.get("offset", 0)))
    state["offset"] = next_offset
    terminal = False
    failed = False
    stale = False
    for event in events:
        kind = event_type(event)
        if kind == "thread.started":
            state["thread_id"] = thread_id_from(event, path.stem)
            state["status"] = "idle"
        elif kind == "turn.started":
            state["status"] = "active"
        elif kind in TERMINAL_TYPES or (kind == "error" and not is_reconnect_notice(event)):
            notification = terminal_event(path, event, next_offset)
            if notification is not None:
                if parse_errors:
                    notification["parse_errors"] = parse_errors
                emit(notification)
                terminal = True
                failed = failed or notification["type"] == "codex_session_failed"
            state["status"] = "failed" if failed else "complete"

    idle_seconds = int(time.time() - path.stat().st_mtime)
    stale_marker = f"{path.stat().st_mtime_ns}:{next_offset}"
    if not terminal and stale_seconds >= 0 and idle_seconds >= stale_seconds:
        if state.get("stale_marker") != stale_marker:
            payload = base_payload("codex_session_stale", path, None, next_offset)
            payload["idle_seconds"] = idle_seconds
            payload["status"] = state.get("status", "unknown")
            if parse_errors:
                payload["parse_errors"] = parse_errors
            emit(payload)
            state["stale_marker"] = stale_marker
            state["status"] = "stale"
            stale = True
    return terminal, failed, stale


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Emit Claude Code monitor notifications for Codex JSONL logs."
    )
    parser.add_argument("run_dir", nargs="?", help="Run directory containing logs/ JSONL files.")
    parser.add_argument("--run-id", help="Run id under .codex-orchestrator/runs.")
    parser.add_argument("--repo", default=".", help="Repository root used with --run-id.")
    parser.add_argument("--log", action="append", help="Explicit JSONL log path. Repeatable.")
    parser.add_argument("--once", action="store_true", help="Scan once and exit.")
    parser.add_argument("--stale-seconds", type=int, default=600, help="Emit stale after this many idle seconds.")
    parser.add_argument("--poll-interval", type=float, default=30.0, help="Seconds between watch scans.")
    parser.add_argument("--max-logs", type=int, default=1, help="Number of newest run logs to watch.")
    parser.add_argument(
        "--fail-on-session-failure",
        action="store_true",
        help="Exit nonzero when the watched Codex session fails.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    auto_mode = not args.run_dir and not args.run_id and not args.log

    states: dict[Path, dict[str, Any]] = {}
    while True:
        paths = resolve_logs(args)
        if auto_mode and not paths:
            if args.once:
                return 0
            time.sleep(max(0.1, args.poll_interval))
            continue
        any_failed = any(bool(state.get("failed")) for state in states.values())
        watched_done = bool(paths)
        for path in paths:
            state = states.setdefault(path, {"offset": 0, "status": "unknown"})
            if state.get("done"):
                continue
            terminal, failed, stale = scan_path(path, state, args.stale_seconds)
            if terminal or stale:
                state["done"] = True
                state["done_reason"] = "terminal" if terminal else "stale"
                state["failed"] = failed
            if failed:
                any_failed = True
            if not state.get("done"):
                watched_done = False
        if args.once:
            return 1 if any_failed and args.fail_on_session_failure else 0
        if paths and watched_done:
            return 1 if any_failed and args.fail_on_session_failure else 0
        time.sleep(max(0.1, args.poll_interval))


if __name__ == "__main__":
    raise SystemExit(main())
