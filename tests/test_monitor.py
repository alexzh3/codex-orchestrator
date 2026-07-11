from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "codex_orch_tools.py"


def run_monitor(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), "monitor", *args],
        check=False,
        text=True,
        capture_output=True,
        cwd=ROOT,
        timeout=5,
    )


def write_jsonl(path: Path, records: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(record) + "\n" for record in records), encoding="utf-8")


def journal_entry(kind: str, **values: object) -> dict[str, object]:
    return {"type": kind, "recorded_at": "2026-07-10T12:00:00Z", **values}


class MonitorTests(unittest.TestCase):
    def make_run(self, root: Path, name: str = "run-active") -> Path:
        run_dir = root / ".codex-orchestrator" / "runs" / name
        run_dir.mkdir(parents=True)
        return run_dir

    def add_execution(
        self,
        run_dir: Path,
        agent: str = "codex-impl-01",
        execution: str = "execution-01",
        events: list[dict[str, object]] | None = None,
    ) -> tuple[dict[str, object], Path]:
        path = run_dir / agent / execution / "events.jsonl"
        write_jsonl(path, events or [])
        record = journal_entry(
            "execution",
            task="task-01",
            agent=agent,
            execution=execution,
            provider="codex",
            prompt=f"{agent}/{execution}/prompt.md",
            events=str(path.relative_to(run_dir)),
            handoff=f"{agent}/{execution}/handoff.md",
            event_source="exec",
        )
        return record, path

    def test_monitor_requires_one_explicit_target(self) -> None:
        cases = (
            run_monitor("--once"),
            run_monitor("--repo", ".", "--once"),
            run_monitor("run", "--log", "events.jsonl", "--once"),
        )

        for result in cases:
            with self.subTest(args=result.args):
                self.assertEqual(result.returncode, 1, result.stderr)
                payload = json.loads(result.stdout)
                self.assertEqual(payload["type"], "monitor_error")

    def test_run_id_selects_a_run_under_the_repository(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run_dir = self.make_run(root, "run-selected")
            execution, _ = self.add_execution(
                run_dir,
                events=[
                    {"type": "thread.started", "thread_id": "selected"},
                    {"type": "turn.completed"},
                ],
            )
            write_jsonl(
                run_dir / "journal.jsonl",
                [journal_entry("run_started", run_id="run-selected"), execution],
            )

            result = run_monitor("--repo", str(root), "--run-id", "run-selected", "--once")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["thread_id"], "selected")

    def test_nonexistent_run_directory_and_run_id_are_errors(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cases = (
                run_monitor(str(root / "missing-run"), "--once"),
                run_monitor("--repo", str(root), "--run-id", "missing", "--once"),
            )

        for result in cases:
            with self.subTest(args=result.args):
                self.assertEqual(result.returncode, 1, result.stderr)
                payload = json.loads(result.stdout)
                self.assertEqual(payload["type"], "monitor_error")
                self.assertIn("run directory", payload["message"])

    def test_watches_all_inflight_executions_but_not_completed_ones(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "run"
            run_dir.mkdir()
            first, _ = self.add_execution(
                run_dir,
                events=[
                    {"type": "thread.started", "thread_id": "first"},
                    {"type": "turn.completed"},
                ],
            )
            second, _ = self.add_execution(
                run_dir,
                agent="codex-review-01",
                events=[
                    {"type": "thread.started", "thread_id": "second"},
                    {"type": "turn.completed"},
                ],
            )
            write_jsonl(
                run_dir / "journal.jsonl",
                [
                    journal_entry("run_started", run_id="run"),
                    first,
                    second,
                    journal_entry(
                        "execution_result",
                        task="task-01",
                        agent="codex-review-01",
                        execution="execution-01",
                        status="complete",
                    ),
                ],
            )

            result = run_monitor(str(run_dir), "--once")

        notifications = [json.loads(line) for line in result.stdout.splitlines()]
        self.assertEqual(len(notifications), 1)
        self.assertEqual(notifications[0]["thread_id"], "first")

    def test_no_codex_targets_returns_without_polling(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "run"
            run_dir.mkdir()
            write_jsonl(
                run_dir / "journal.jsonl",
                [
                    journal_entry("run_started", run_id="run"),
                    journal_entry(
                        "execution",
                        agent="codex-impl-01",
                        execution="execution-01",
                    ),
                    journal_entry(
                        "execution_result",
                        agent="codex-impl-01",
                        execution="execution-01",
                        status="complete",
                    ),
                    journal_entry(
                        "execution",
                        agent="claude-review-01",
                        execution="execution-01",
                        event_source="claude",
                    ),
                ],
            )

            result = run_monitor(str(run_dir))

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "")

    def test_non_exec_journal_stream_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "run"
            run_dir.mkdir()
            execution, _ = self.add_execution(run_dir)
            execution["event_source"] = "ide"
            write_jsonl(
                run_dir / "journal.jsonl",
                [journal_entry("run_started", run_id="run"), execution],
            )

            result = run_monitor(str(run_dir), "--once")

        self.assertEqual(result.returncode, 1, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["type"], "monitor_error")
        self.assertIn("only managed exec streams", payload["message"])

    def test_explicit_file_alias_and_failure_exit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "failed.jsonl"
            write_jsonl(path, [{"type": "turn.failed", "error": {"message": "boom"}}])
            result = run_monitor(
                "--file", str(path), "--once", "--fail-on-session-failure"
            )

        self.assertEqual(result.returncode, 1)
        self.assertEqual(json.loads(result.stdout)["type"], "codex_session_failed")

    def test_latest_exec_signal_emits_one_notification_with_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "events.jsonl"
            write_jsonl(
                path,
                [
                    {"type": "thread.started", "thread_id": "native-thread"},
                    {
                        "type": "turn.failed",
                        "turn_id": "turn-1",
                        "error": {"message": "old failure"},
                    },
                    {
                        "type": "turn.completed",
                        "turn_id": "turn-2",
                        "usage": {"input_tokens": 20, "output_tokens": 5},
                    },
                ],
            )
            result = run_monitor("--log", str(path), "--once")

        notifications = [json.loads(line) for line in result.stdout.splitlines()]
        self.assertEqual(len(notifications), 1)
        self.assertEqual(notifications[0]["type"], "codex_session_complete")
        self.assertEqual(notifications[0]["thread_id"], "native-thread")
        self.assertEqual(notifications[0]["turn_id"], "turn-2")
        self.assertEqual(notifications[0]["usage"]["output_tokens"], 5)

    def test_complete_final_event_does_not_require_a_trailing_newline(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "events.jsonl"
            path.write_text(
                '{"type":"turn.completed","thread_id":"complete"}', encoding="utf-8"
            )
            result = run_monitor("--log", str(path), "--once")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["type"], "codex_session_complete")

    def test_stale_stream_is_reported(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "active.jsonl"
            write_jsonl(path, [{"type": "turn.started", "thread_id": "stale-thread"}])
            old = time.time() - 20
            os.utime(path, (old, old))
            result = run_monitor("--log", str(path), "--once", "--stale-seconds", "1")

        notification = json.loads(result.stdout)
        self.assertEqual(notification["type"], "codex_session_stale")
        self.assertGreaterEqual(notification["idle_seconds"], 1)

    def test_watch_mode_polls_until_a_terminal_event(self) -> None:
        cases = (
            ("turn.completed", "codex_session_complete", 0),
            ("turn.failed", "codex_session_failed", 1),
        )
        for terminal_event, notification_type, expected_code in cases:
            with self.subTest(terminal_event=terminal_event), tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / "events.jsonl"
                write_jsonl(
                    path,
                    [{"type": "thread.started", "thread_id": "watched"}, {"type": "turn.started"}],
                )
                process = subprocess.Popen(
                    [
                        sys.executable,
                        str(SCRIPT),
                        "monitor",
                        "--log",
                        str(path),
                        "--poll-interval",
                        "0.05",
                        "--stale-seconds",
                        "-1",
                        "--fail-on-session-failure",
                    ],
                    text=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    cwd=ROOT,
                )
                try:
                    time.sleep(0.15)
                    with path.open("a", encoding="utf-8") as handle:
                        handle.write(json.dumps({"type": terminal_event}) + "\n")
                    stdout, stderr = process.communicate(timeout=5)
                finally:
                    if process.poll() is None:
                        process.kill()
                        process.wait()

                self.assertEqual(process.returncode, expected_code, stderr)
                self.assertEqual(json.loads(stdout)["type"], notification_type)

    def test_watch_mode_handles_a_replaced_stream(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "events.jsonl"
            write_jsonl(path, [{"type": "turn.started"}])
            process = subprocess.Popen(
                [
                    sys.executable,
                    str(SCRIPT),
                    "monitor",
                    "--log",
                    str(path),
                    "--poll-interval",
                    "0.05",
                    "--stale-seconds",
                    "-1",
                ],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=ROOT,
            )
            try:
                time.sleep(0.15)
                replacement = Path(tmp) / "replacement.jsonl"
                write_jsonl(
                    replacement,
                    [
                        {"type": "thread.started", "thread_id": "replacement"},
                        {"type": "turn.completed"},
                    ],
                )
                replacement.replace(path)
                stdout, stderr = process.communicate(timeout=5)
            finally:
                if process.poll() is None:
                    process.kill()
                    process.wait()

        self.assertEqual(process.returncode, 0, stderr)
        self.assertEqual(json.loads(stdout)["thread_id"], "replacement")

    def test_monitor_reports_parse_errors_with_a_terminal_event(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "events.jsonl"
            path.write_text(
                'not json\n{"type":"turn.completed","thread_id":"parsed"}\n',
                encoding="utf-8",
            )
            result = run_monitor("--log", str(path), "--once")

        notification = json.loads(result.stdout)
        self.assertEqual(notification["type"], "codex_session_complete")
        self.assertEqual(notification["parse_errors"], 1)

    def test_low_parser_confidence_is_terminal(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "events.jsonl"
            write_jsonl(path, [{"type": "future.one"}, {"type": "future.two"}])
            result = run_monitor("--log", str(path), "--once")

        self.assertEqual(result.returncode, 2, result.stderr)
        notification = json.loads(result.stdout)
        self.assertEqual(notification["type"], "codex_session_unknown")
        self.assertEqual(notification["compatibility"]["parse_confidence"], "low")

    def test_explicit_missing_log_is_an_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "missing-events.jsonl"
            result = run_monitor("--log", str(path), "--once")

        self.assertEqual(result.returncode, 1)
        notification = json.loads(result.stdout)
        self.assertEqual(notification["type"], "monitor_error")
        self.assertEqual(notification["path"], str(path))
        self.assertIn("does not exist", notification["message"])

    def test_journal_declared_missing_or_directory_stream_is_an_error(self) -> None:
        for path_kind in ("missing", "directory"):
            with self.subTest(path_kind=path_kind), tempfile.TemporaryDirectory() as tmp:
                run_dir = Path(tmp) / "run"
                run_dir.mkdir()
                path = run_dir / "codex-impl-01" / "execution-01" / "events.jsonl"
                if path_kind == "directory":
                    path.mkdir(parents=True)
                execution = journal_entry(
                    "execution",
                    task="task-01",
                    agent="codex-impl-01",
                    execution="execution-01",
                    events=str(path.relative_to(run_dir)),
                )
                write_jsonl(
                    run_dir / "journal.jsonl",
                    [journal_entry("run_started", run_id="run"), execution],
                )

                result = run_monitor(str(run_dir), "--once")

            self.assertEqual(result.returncode, 1, result.stderr)
            notification = json.loads(result.stdout)
            self.assertEqual(notification["type"], "monitor_error")
            self.assertEqual(notification["path"], str(path.resolve()))

    def test_missing_events_field_and_invalid_journal_are_errors(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "run"
            run_dir.mkdir()
            write_jsonl(
                run_dir / "journal.jsonl",
                [
                    journal_entry("run_started", run_id="run"),
                    journal_entry(
                        "execution", agent="codex-impl-01", execution="execution-01"
                    ),
                ],
            )
            missing_events = run_monitor(str(run_dir), "--once")
            (run_dir / "journal.jsonl").write_text("not json\n", encoding="utf-8")
            invalid_journal = run_monitor(str(run_dir), "--once")

        for result in (missing_events, invalid_journal):
            with self.subTest(stdout=result.stdout):
                self.assertEqual(result.returncode, 1, result.stderr)
                self.assertEqual(json.loads(result.stdout)["type"], "monitor_error")


if __name__ == "__main__":
    unittest.main()
