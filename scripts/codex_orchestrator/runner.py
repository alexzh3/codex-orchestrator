"""Capture a Codex JSONL stream while rendering compact progress."""

from __future__ import annotations

import argparse
import os
import queue
import re
import signal
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, TextIO

from .events import (
    PARSE_ERROR_TYPES,
    decode_event_line,
    event_text,
    is_reconnect_notice,
    json_dumps,
)
from .role_config import ROLES, RoleConfigError, RolePolicy, load_role_config

_ANSI_RE = re.compile(
    r"\x1b(?:\][^\x07]*(?:\x07|\x1b\\)|\[[0-?]*[ -/]*[@-~]|[@-_])"
)
_ASSIGNMENT_SECRET_RE = re.compile(
    r"(?i)(?<![A-Za-z0-9_.-])"
    r"(?P<quoted_key>[\"']?"
    r"[A-Za-z0-9_.-]*(?:api[_-]?key|authorization|password|secret|token)"
    r"[A-Za-z0-9_.-]*[\"']?)"
    r"\s*(?P<separator>[=:])\s*"
    r"(?!\[redacted\])"
    r"(?:Bearer\s+[^\s,;]+|\"(?:\\.|[^\"\\])*\"|'(?:\\.|[^'\\])*'|[^\s,;}\]]+)"
)
_SPACED_SECRET_RE = re.compile(
    r"(?i)(?<![A-Za-z0-9_.-])"
    r"(?P<flag>-{0,2}[A-Za-z0-9_.-]*"
    r"(?:api[_-]?key|authorization|password|secret|token)"
    r"[A-Za-z0-9_.-]*)"
    r"\s+"
    r"(?:Bearer\s+\S+|\"(?:\\.|[^\"\\])*\"|'(?:\\.|[^'\\])*'|(?!-)\S+)"
)
_BEARER_SECRET_RE = re.compile(r"(?i)\bBearer\s+(?:\"[^\"]*\"|'[^']*'|\S+)")
_WHITESPACE_RE = re.compile(r"\s+")
_CONTROL_CHARS = dict.fromkeys([*range(32), 127], " ")
_TEXT_LIMIT = 160
_TERMINATE_TIMEOUT = 5.0
_DISPLAY_QUEUE_SIZE = 256
_DISPLAY_JOIN_TIMEOUT = 0.2
_DISPLAY_BACKLOG_WARNING = "warning: display backlogged; progress lines dropped"
_PERFORMANCE_CONFIG_KEYS = {
    "features.fast_mode",
    "model",
    "model_reasoning_effort",
    "service_tier",
}


def scrub_text(value: object) -> str:
    """Strip ANSI, redact secrets, collapse whitespace, and coerce to ASCII."""

    text = value if isinstance(value, str) else str(value)
    text = _ANSI_RE.sub("", text)
    text = text.translate(_CONTROL_CHARS)
    text = _ASSIGNMENT_SECRET_RE.sub(
        lambda match: f"{match.group('quoted_key')}{match.group('separator')}[redacted]",
        text,
    )
    text = _SPACED_SECRET_RE.sub(
        lambda match: f"{match.group('flag')} [redacted]",
        text,
    )
    text = _BEARER_SECRET_RE.sub("Bearer [redacted]", text)
    text = _WHITESPACE_RE.sub(" ", text).strip()
    return text.encode("ascii", errors="backslashreplace").decode("ascii")


def sanitize_text(value: object) -> str:
    """Scrub event-provided text and truncate it to the display budget."""

    text = scrub_text(value)
    if len(text) > _TEXT_LIMIT:
        return text[: _TEXT_LIMIT - 3] + "..."
    return text


def _value_text(value: object) -> str:
    if isinstance(value, str):
        return value
    try:
        return json_dumps(value)
    except (TypeError, ValueError):
        return str(value)


@dataclass
class _TodoState:
    texts: tuple[str, ...]
    completed: dict[tuple[str, int], bool]
    reported_done: set[tuple[str, int]]


class EventRenderer:
    """Turn individual Codex JSONL records into compact display messages."""

    def __init__(self) -> None:
        self._warned: set[str] = set()
        self._todos: dict[str, _TodoState] = {}

    def render_bytes(self, line: bytes) -> list[str]:
        try:
            decoded = line.decode("utf-8")
        except UnicodeDecodeError:
            return self._unparseable_warning()
        return self.render(decoded)

    def render(self, line: str) -> list[str]:
        record = decode_event_line(line)
        if record is None or record.event_type in PARSE_ERROR_TYPES:
            return self._unparseable_warning()

        event = record.event
        kind = record.event_type
        if kind == "thread.started":
            return [f"thread started {sanitize_text(_value_text(event.get('thread_id')))}"]
        if kind == "turn.started":
            return ["turn started"]
        if kind == "turn.completed":
            return [self._turn_completed(event)]
        if kind == "turn.failed":
            error = event.get("error")
            if error is None:
                error = event_text(event)
            return [f"turn failed: {sanitize_text(_value_text(error))}"]
        if kind == "error":
            prefix = "warning" if is_reconnect_notice(record) else "error"
            return [f"{prefix}: {sanitize_text(event_text(event))}"]
        if kind in {"item.started", "item.updated", "item.completed"}:
            return self._render_item(kind, event.get("item"))
        return self._warn_once(
            f"event:{kind}", f"warning: unknown event type {sanitize_text(kind)}"
        )

    def _unparseable_warning(self) -> list[str]:
        return self._warn_once("unparseable", "warning: unparseable event line")

    def _warn_once(self, key: str, message: str) -> list[str]:
        if key in self._warned:
            return []
        self._warned.add(key)
        return [message]

    def _turn_completed(self, event: dict[str, object]) -> str:
        parts = ["turn completed"]
        usage = event.get("usage")
        if isinstance(usage, dict):
            for field, label in (
                ("input_tokens", "input"),
                ("cached_input_tokens", "cached"),
                ("output_tokens", "output"),
            ):
                if field in usage:
                    parts.append(f"{label}={sanitize_text(_value_text(usage[field]))}")
        return " ".join(parts)

    def _render_item(self, event_kind: str, value: object) -> list[str]:
        if not isinstance(value, dict):
            return self._unknown_item("<missing>")
        item = value
        item_type = item.get("type")
        if not isinstance(item_type, str):
            return self._unknown_item("<missing>")

        if item_type == "command_execution":
            if event_kind == "item.started":
                command = sanitize_text(_value_text(item.get("command")))
                return [f"command started: {command}"]
            if event_kind == "item.completed":
                exit_code = item.get("exit_code")
                if exit_code is not None:
                    return [f"command completed exit={sanitize_text(_value_text(exit_code))}"]
                return [
                    "command completed "
                    f"status={sanitize_text(_value_text(item.get('status')))}"
                ]
            return []
        if item_type == "file_change":
            return self._file_change(event_kind, item)
        if item_type == "mcp_tool_call":
            return self._mcp_call(event_kind, item)
        if item_type == "web_search":
            if event_kind != "item.completed":
                return []
            return [f"web search: {sanitize_text(_value_text(item.get('query')))}"]
        if item_type == "todo_list":
            return self._todo_list(item)
        if item_type == "error":
            message = item.get("message")
            if message is None:
                message = item.get("error")
            return [f"warning: {sanitize_text(_value_text(message))}"]
        if item_type in {"agent_message", "reasoning"}:
            return []
        return self._unknown_item(item_type)

    def _unknown_item(self, item_type: str) -> list[str]:
        return self._warn_once(
            f"item:{item_type}", f"warning: unknown item type {sanitize_text(item_type)}"
        )

    def _file_change(self, event_kind: str, item: dict[str, object]) -> list[str]:
        if event_kind != "item.completed":
            return []
        changes = item.get("changes")
        if not isinstance(changes, list):
            changes = []
        descriptions = []
        for change in changes[:5]:
            if not isinstance(change, dict):
                descriptions.append(_value_text(change))
                continue
            descriptions.append(
                f"{_value_text(change.get('kind'))} {_value_text(change.get('path'))}"
            )
        description = sanitize_text(", ".join(descriptions))
        omitted = len(changes) - 5
        suffix = f", +{omitted} more" if omitted > 0 else ""
        return [f"files completed: {description}{suffix}"]

    def _mcp_call(self, event_kind: str, item: dict[str, object]) -> list[str]:
        name = sanitize_text(
            f"{_value_text(item.get('server'))}.{_value_text(item.get('tool'))}"
        )
        if event_kind == "item.started":
            return [f"mcp started: {name}"]
        if event_kind == "item.completed":
            status = sanitize_text(_value_text(item.get("status")))
            return [f"mcp completed: {name} status={status}"]
        return []

    def _todo_list(self, item: dict[str, object]) -> list[str]:
        item_id = _value_text(item.get("id"))
        raw_items = item.get("items")
        if not isinstance(raw_items, list):
            raw_items = []

        entries: list[tuple[str, bool]] = []
        for raw_item in raw_items:
            if not isinstance(raw_item, dict):
                entries.append((_value_text(raw_item), False))
                continue
            entries.append((_value_text(raw_item.get("text")), raw_item.get("completed") is True))

        occurrence_counts: dict[str, int] = {}
        current: dict[tuple[str, int], bool] = {}
        for text, completed in entries:
            occurrence = occurrence_counts.get(text, 0)
            occurrence_counts[text] = occurrence + 1
            current[(text, occurrence)] = completed

        texts = tuple(text for text, _ in entries)
        previous = self._todos.get(item_id)
        reported = set() if previous is None else set(previous.reported_done)
        messages = []
        if previous is None or previous.texts != texts:
            messages.append(f"todo plan: {len(entries)} items")
        if previous is not None:
            for key, completed in current.items():
                if previous.completed.get(key) is False and completed and key not in reported:
                    messages.append(f"todo done: {sanitize_text(key[0])}")
                    reported.add(key)

        self._todos[item_id] = _TodoState(texts, current, reported)
        return messages


class _Display:
    def __init__(self, label: str, started: float, stream: TextIO) -> None:
        self._label = sanitize_text(label)
        self._started = started
        self._stream = stream
        try:
            self._stream_fd: int | None = os.dup(stream.fileno())
        except (AttributeError, OSError, ValueError):
            self._stream_fd = None
        self._enabled = True
        self._closed = False
        self._dropped = threading.Event()
        self._queue: queue.Queue[str | None] = queue.Queue(maxsize=_DISPLAY_QUEUE_SIZE)
        self._writer = threading.Thread(
            target=self._write_lines,
            name="codex-display-writer",
            daemon=True,
        )
        self._writer.start()

    def emit(self, message: str) -> None:
        if not self._enabled or self._closed:
            return
        line = self._format_line(message)
        try:
            self._queue.put_nowait(line)
        except queue.Full:
            self._dropped.set()

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        while True:
            try:
                self._queue.put_nowait(None)
                break
            except queue.Full:
                self._dropped.set()
                try:
                    self._queue.get_nowait()
                except queue.Empty:
                    pass
        self._writer.join(timeout=_DISPLAY_JOIN_TIMEOUT)

    def _format_line(self, message: str) -> str:
        elapsed = max(0, int(time.monotonic() - self._started))
        hours, remainder = divmod(elapsed, 3600)
        minutes, seconds = divmod(remainder, 60)
        # Scrubbing is idempotent; rescrubbing here guarantees structurally
        # that no renderer path can leak ANSI or secrets to the display.
        return f"{hours:02d}:{minutes:02d}:{seconds:02d} {self._label} {scrub_text(message)}\n"

    def _write_lines(self) -> None:
        backlog_warned = False
        try:
            while self._enabled:
                line = self._queue.get()
                if line is None:
                    return
                if not self._write_line(line):
                    return
                if self._dropped.is_set() and not backlog_warned:
                    backlog_warned = True
                    if not self._write_line(self._format_line(_DISPLAY_BACKLOG_WARNING)):
                        return
        finally:
            if self._stream_fd is not None:
                try:
                    os.close(self._stream_fd)
                except OSError:
                    pass

    def _write_line(self, line: str) -> bool:
        try:
            if self._stream_fd is None:
                self._stream.write(line)
                self._stream.flush()
            else:
                remaining = line.encode("ascii")
                while remaining:
                    remaining = remaining[os.write(self._stream_fd, remaining) :]
        except (OSError, ValueError):
            self._enabled = False
            self._redirect_broken_stream()
            return False
        return True

    def _redirect_broken_stream(self) -> None:
        # Capture continues after display fails, so interpreter-exit buffer
        # flushes must not raise into stderr from the dead descriptor.
        try:
            stream_fd = self._stream.fileno()
            null_fd = os.open(os.devnull, os.O_WRONLY)
        except (AttributeError, OSError, ValueError):
            return
        try:
            os.dup2(null_fd, stream_fd)
        except OSError:
            pass
        finally:
            os.close(null_fd)


def _process_group_exists(process_group: int) -> bool:
    try:
        os.killpg(process_group, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _stop_child(process: subprocess.Popen[bytes]) -> None:
    """Terminate the child tree, escalating after a short grace period."""

    if os.name != "posix":
        if process.poll() is not None:
            return
        try:
            process.terminate()
        except OSError:
            pass
        try:
            process.wait(timeout=_TERMINATE_TIMEOUT)
        except subprocess.TimeoutExpired:
            try:
                process.kill()
            except OSError:
                pass
            process.wait()
        return

    process_group = process.pid
    try:
        os.killpg(process_group, signal.SIGTERM)
    except ProcessLookupError:
        process.poll()
        return

    deadline = time.monotonic() + _TERMINATE_TIMEOUT
    while time.monotonic() < deadline:
        process.poll()
        if not _process_group_exists(process_group):
            return
        time.sleep(0.05)

    try:
        os.killpg(process_group, signal.SIGKILL)
    except ProcessLookupError:
        pass
    try:
        process.wait(timeout=1.0)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()


def _kill_child(process: subprocess.Popen[bytes]) -> None:
    """Kill a child tree if its leader is still running."""

    if process.poll() is not None:
        return
    try:
        if os.name == "posix":
            os.killpg(process.pid, signal.SIGKILL)
        else:
            process.kill()
    except OSError:
        pass


def _stop_child_async(process: subprocess.Popen[bytes]) -> threading.Timer | None:
    """Request termination and arm a non-blocking kill escalation."""

    if process.poll() is not None:
        return None
    try:
        if os.name == "posix":
            os.killpg(process.pid, signal.SIGTERM)
        else:
            process.terminate()
    except OSError:
        pass

    timer = threading.Timer(_TERMINATE_TIMEOUT, _kill_child, args=(process,))
    timer.daemon = True
    timer.start()
    return timer


def _write_prompt(process: subprocess.Popen[bytes], prompt: bytes, errors: list[OSError]) -> None:
    if process.stdin is None:
        return
    try:
        process.stdin.write(prompt)
        process.stdin.flush()
    except BrokenPipeError as exc:
        errors.append(exc)
    except OSError as exc:
        errors.append(exc)
    finally:
        try:
            process.stdin.close()
        except BrokenPipeError:
            pass
        except OSError as exc:
            errors.append(exc)


def _run_child(
    command: list[str],
    prompt: bytes,
    events: BinaryIO,
    label: str,
    started: float,
) -> int:
    cancelled_signal: int | None = None
    process: subprocess.Popen[bytes] | None = None
    termination_timer: threading.Timer | None = None

    def handle_signal(signum: int, _frame: object) -> None:
        nonlocal cancelled_signal, termination_timer
        if cancelled_signal is None:
            cancelled_signal = signum
        if process is not None and termination_timer is None:
            termination_timer = _stop_child_async(process)

    previous_handlers = {
        signum: signal.signal(signum, handle_signal)
        for signum in (signal.SIGINT, signal.SIGTERM)
    }
    try:
        try:
            process = subprocess.Popen(
                command,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=None,
                start_new_session=os.name == "posix",
            )
        except OSError as exc:
            print(f"run: could not launch child: {exc}", file=sys.stderr)
            return 1
        if cancelled_signal is not None and termination_timer is None:
            _stop_child(process)

        prompt_errors: list[OSError] = []
        writer = threading.Thread(
            target=_write_prompt,
            args=(process, prompt, prompt_errors),
            name="codex-prompt-writer",
        )
        writer.start()

        renderer = EventRenderer()
        display = _Display(label, started, sys.stdout)
        runner_error: str | None = None
        progress_failed = False
        try:
            try:
                if process.stdout is None:
                    runner_error = "child stdout pipe was not created"
                    _stop_child(process)
                else:
                    while True:
                        try:
                            chunk = process.stdout.readline()
                        except OSError as exc:
                            if cancelled_signal is None:
                                runner_error = f"could not read child stdout: {exc}"
                            _stop_child(process)
                            break
                        if chunk == b"":
                            break
                        try:
                            events.write(chunk)
                            events.flush()
                        except OSError as exc:
                            runner_error = f"could not write events file: {exc}"
                            _stop_child(process)
                            break
                        if progress_failed:
                            continue
                        try:
                            for message in renderer.render_bytes(chunk):
                                display.emit(message)
                        except Exception:
                            progress_failed = True
                            try:
                                display.emit(
                                    "warning: progress rendering failed; "
                                    "further progress suppressed"
                                )
                            except Exception:
                                pass
                child_code = process.wait()
            finally:
                if termination_timer is not None and process.poll() is not None:
                    termination_timer.cancel()
                writer.join()
                if process.stdout is not None:
                    process.stdout.close()

            if prompt_errors and runner_error is None and cancelled_signal is None:
                runner_error = f"could not write child stdin: {prompt_errors[0]}"
            normalized_child_code = 128 - child_code if child_code < 0 else child_code
            if not progress_failed:
                display.emit(f"exited code={normalized_child_code}")
        finally:
            display.close()
        if runner_error is not None:
            print(f"run: {runner_error}", file=sys.stderr)
            return 1
        if cancelled_signal is not None:
            return 128 + cancelled_signal
        return normalized_child_code
    finally:
        for signum, previous_handler in previous_handlers.items():
            signal.signal(signum, previous_handler)


def _configured_command(
    command: list[str], policy: RolePolicy, reasoning_effort: str
) -> list[str]:
    if (
        len(command) < 2
        or Path(command[0]).name not in {"codex", "codex.exe"}
        or command[1] != "exec"
    ):
        raise RoleConfigError("active role configuration requires a 'codex exec' child command")
    if reasoning_effort not in policy.reasoning_efforts:
        allowed = ", ".join(policy.reasoning_efforts)
        raise RoleConfigError(
            f"reasoning effort {reasoning_effort!r} is not allowed for this role; "
            f"choose one of: {allowed}"
        )
    _reject_performance_conflicts(command)

    overrides: list[str] = []
    if policy.model is not None:
        overrides.extend(("--model", policy.model))
    overrides.extend(("-c", f'model_reasoning_effort="{reasoning_effort}"'))
    if policy.speed == "fast":
        overrides.extend(("-c", 'service_tier="fast"', "--enable", "fast_mode"))
    return [*command[:2], *overrides, *command[2:]]


def _reject_performance_conflicts(command: list[str]) -> None:
    index = 2
    while index < len(command):
        argument = command[index]
        if argument == "--":
            return
        if (
            argument in {"-m", "--model"}
            or (argument.startswith("-m") and len(argument) > 2)
            or argument.startswith("--model=")
        ):
            raise RoleConfigError(f"child command contains conflicting option {argument!r}")
        if argument in {"-c", "--config"}:
            if index + 1 < len(command):
                _reject_performance_config_value(command[index + 1])
                index += 2
                continue
        elif argument.startswith("--config="):
            _reject_performance_config_value(argument.split("=", 1)[1])
        elif argument.startswith("-c") and len(argument) > 2:
            _reject_performance_config_value(argument[2:].removeprefix("="))
        if argument in {"--enable", "--disable"}:
            if index + 1 < len(command) and command[index + 1] == "fast_mode":
                raise RoleConfigError(
                    f"child command contains conflicting option {argument!r} for fast_mode"
                )
            index += 2
            continue
        if argument in {"--enable=fast_mode", "--disable=fast_mode"}:
            raise RoleConfigError(f"child command contains conflicting option {argument!r}")
        index += 1


def _reject_performance_config_value(value: str) -> None:
    key = value.split("=", 1)[0].strip()
    if key in _PERFORMANCE_CONFIG_KEYS:
        raise RoleConfigError(f"child command contains conflicting config override {key!r}")


def command_run(argv: list[str]) -> int:
    """Parse run-only flags and execute the untouched command after the first ``--``."""

    parser = argparse.ArgumentParser(prog=f"{Path(sys.argv[0]).name} run")
    parser.add_argument("--events", required=True, help="Raw child stdout capture path.")
    parser.add_argument("--prompt", required=True, help="Prompt bytes sent to child stdin.")
    parser.add_argument("--label", default="codex", help="Progress-line label.")
    parser.add_argument("--repo", help="Repository root containing the opt-in role policy.")
    parser.add_argument("--role", choices=ROLES, help="Orchestration role for this execution.")
    parser.add_argument(
        "--reasoning-effort", help="Concrete effort selected from the role's allowed values."
    )

    try:
        separator = argv.index("--")
    except ValueError:
        separator = len(argv)
    args = parser.parse_args(argv[:separator])
    command = argv[separator + 1 :] if separator < len(argv) else []
    if not command:
        parser.error("a child command is required after --")

    try:
        config = load_role_config(Path(args.repo)) if args.repo is not None else None
        if config is None:
            if args.reasoning_effort is not None:
                raise RoleConfigError(
                    "--reasoning-effort requires an active repository role configuration"
                )
        else:
            if args.role is None:
                raise RoleConfigError("--role is required when role configuration is active")
            if args.reasoning_effort is None:
                raise RoleConfigError(
                    "--reasoning-effort is required when role configuration is active"
                )
            command = _configured_command(
                command, config.policy_for(args.role), args.reasoning_effort
            )
    except RoleConfigError as exc:
        print(f"run: {exc}", file=sys.stderr)
        return 2

    started = time.monotonic()
    prompt_path = Path(args.prompt)
    try:
        prompt = prompt_path.read_bytes()
    except OSError as exc:
        print(f"run: could not read prompt {prompt_path}: {exc}", file=sys.stderr)
        return 1

    events_path = Path(args.events)
    try:
        events = events_path.open("xb")
    except OSError as exc:
        print(f"run: could not create events file {events_path}: {exc}", file=sys.stderr)
        return 1

    result = 1
    close_error: OSError | None = None
    try:
        result = _run_child(command, prompt, events, args.label, started)
    finally:
        try:
            events.close()
        except OSError as exc:
            close_error = exc
    if close_error is not None:
        print(f"run: could not close events file: {close_error}", file=sys.stderr)
        return 1
    return result
