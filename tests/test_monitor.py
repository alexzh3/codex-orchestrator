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
    command = [sys.executable, str(SCRIPT), "monitor"]
    return subprocess.run(
        [*command, *args],
        check=False,
        text=True,
        capture_output=True,
        cwd=ROOT,
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
        event_path: Path | None = None,
        source: str = "exec",
    ) -> tuple[dict[str, object], Path]:
        path = event_path or run_dir / agent / execution / "events.jsonl"
        write_jsonl(path, events or [])
        value = (
            str(path)
            if path.is_absolute() and not path.is_relative_to(run_dir)
            else str(path.relative_to(run_dir))
        )
        record = journal_entry(
            "execution",
            task="task-01",
            agent=agent,
            execution=execution,
            provider="codex",
            prompt=f"{agent}/{execution}/prompt.md",
            events=value,
            handoff=f"{agent}/{execution}/handoff.md",
            event_source=source,
        )
        return record, path

    def test_auto_discovers_active_run_and_ignores_newer_closed_run(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            active = self.make_run(root)
            execution, _ = self.add_execution(
                active,
                events=[
                    {"type": "thread.started", "thread_id": "thread-active"},
                    {"type": "turn.completed", "thread_id": "thread-active"},
                ],
            )
            write_jsonl(
                active / "journal.jsonl",
                [journal_entry("run_started", run_id="run-active"), execution],
            )

            closed = self.make_run(root, "run-closed")
            closed_execution, closed_events = self.add_execution(closed)
            write_jsonl(
                closed / "journal.jsonl",
                [
                    journal_entry("run_started", run_id="run-closed"),
                    closed_execution,
                    journal_entry("run_closed", judgment="passed"),
                ],
            )
            now = time.time() + 10
            os.utime(closed_events, (now, now))

            result = run_monitor("--repo", str(root), "--once")

        self.assertEqual(result.returncode, 0, result.stderr)
        notifications = [json.loads(line) for line in result.stdout.splitlines()]
        self.assertEqual([item["type"] for item in notifications], ["codex_session_complete"])
        self.assertEqual(notifications[0]["thread_id"], "thread-active")
        self.assertEqual(notifications[0]["agent"], "codex-impl-01")
        self.assertEqual(notifications[0]["execution"], "execution-01")

    def test_run_id_selects_a_run_under_the_repository(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run_dir = self.make_run(root, "run-selected")
            execution, _ = self.add_execution(
                run_dir,
                events=[{"type": "turn.completed", "thread_id": "selected"}],
            )
            write_jsonl(
                run_dir / "journal.jsonl",
                [journal_entry("run_started", run_id="run-selected"), execution],
            )

            result = run_monitor(
                "--repo", str(root), "--run-id", "run-selected", "--once"
            )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["thread_id"], "selected")

    def test_watches_all_inflight_executions_but_not_completed_ones(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "run"
            run_dir.mkdir()
            first, _ = self.add_execution(
                run_dir,
                execution="execution-01",
                events=[{"type": "turn.completed", "thread_id": "first"}],
            )
            second, _ = self.add_execution(
                run_dir,
                agent="codex-review-01",
                execution="execution-01",
                events=[{"type": "turn.completed", "thread_id": "second"}],
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

    def test_external_ide_rollout_is_watched(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run_dir = root / "run"
            run_dir.mkdir()
            rollout = root / "sessions" / "rollout-external.jsonl"
            execution, _ = self.add_execution(
                run_dir,
                event_path=rollout,
                source="ide",
                events=[
                    {
                        "payload": {
                            "type": "thread_goal_updated",
                            "goal": {"status": "complete", "text": "Finished"},
                        }
                    }
                ],
            )
            write_jsonl(
                run_dir / "journal.jsonl",
                [journal_entry("run_started", run_id="run"), execution],
            )

            result = run_monitor(str(run_dir), "--once")

        notification = json.loads(result.stdout)
        self.assertEqual(notification["type"], "codex_session_complete")
        self.assertEqual(notification["source"], "ide")
        self.assertEqual(notification["path"], str(rollout))

    def test_blocked_ide_goal_emits_a_terminal_notification(self) -> None:
        for goal_status in ("blocked", "awaiting-approval"):
            with self.subTest(goal_status=goal_status), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                run_dir = root / "run"
                run_dir.mkdir()
                rollout = root / "sessions" / "rollout-external.jsonl"
                execution, _ = self.add_execution(
                    run_dir,
                    event_path=rollout,
                    source="ide",
                    events=[
                        {
                            "payload": {
                                "type": "thread_goal_updated",
                                "goal": {
                                    "status": goal_status,
                                    "text": "Needs user approval",
                                },
                            }
                        }
                    ],
                )
                write_jsonl(
                    run_dir / "journal.jsonl",
                    [journal_entry("run_started", run_id="run"), execution],
                )

                result = run_monitor(str(run_dir), "--once")

            self.assertEqual(result.returncode, 0, result.stderr)
            notification = json.loads(result.stdout)
            self.assertEqual(notification["type"], "codex_session_blocked")
            self.assertEqual(notification["goal_status"], goal_status)
            self.assertEqual(notification["goal_text"], "Needs user approval")

    def test_ide_monitor_uses_latest_goal_state_in_baseline(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run_dir = root / "run"
            run_dir.mkdir()
            rollout = root / "sessions" / "rollout-external.jsonl"
            execution, _ = self.add_execution(
                run_dir,
                event_path=rollout,
                source="ide",
                events=[
                    {
                        "payload": {
                            "type": "thread_goal_updated",
                            "goal": {"status": "complete", "text": "Old task"},
                        }
                    },
                    {
                        "payload": {
                            "type": "thread_goal_updated",
                            "goal": {"status": "active", "text": "Current task"},
                        }
                    },
                ],
            )
            write_jsonl(
                run_dir / "journal.jsonl",
                [journal_entry("run_started", run_id="run"), execution],
            )

            result = run_monitor(str(run_dir), "--once", "--stale-seconds", "-1")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "")

    def test_explicit_file_alias_and_failure_exit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "failed.jsonl"
            write_jsonl(path, [{"type": "turn.failed", "error": {"message": "boom"}}])
            result = run_monitor(
                "--file",
                str(path),
                "--source",
                "exec",
                "--once",
                "--fail-on-session-failure",
            )

        self.assertEqual(result.returncode, 1)
        self.assertEqual(json.loads(result.stdout)["type"], "codex_session_failed")

    def test_latest_exec_signal_emits_one_notification_with_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "events.jsonl"
            write_jsonl(
                path,
                [
                    {
                        "type": "turn.failed",
                        "thread_id": "thread-1",
                        "turn_id": "turn-1",
                        "error": {"message": "old failure"},
                    },
                    {
                        "type": "turn.completed",
                        "thread_id": "thread-1",
                        "turn_id": "turn-2",
                        "usage": {"input_tokens": 20, "output_tokens": 5},
                    },
                ],
            )
            result = run_monitor("--log", str(path), "--source", "exec", "--once")

        notifications = [json.loads(line) for line in result.stdout.splitlines()]
        self.assertEqual(len(notifications), 1)
        self.assertEqual(notifications[0]["type"], "codex_session_complete")
        self.assertEqual(notifications[0]["thread_id"], "thread-1")
        self.assertEqual(notifications[0]["turn_id"], "turn-2")
        self.assertEqual(notifications[0]["usage"]["output_tokens"], 5)

    def test_complete_final_event_does_not_require_a_trailing_newline(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "events.jsonl"
            path.write_text(
                '{"type":"turn.completed","thread_id":"complete"}',
                encoding="utf-8",
            )
            result = run_monitor("--log", str(path), "--source", "exec", "--once")

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
                write_jsonl(path, [{"type": "turn.started", "thread_id": "watched"}])
                process = subprocess.Popen(
                    [
                        sys.executable,
                        str(SCRIPT),
                        "monitor",
                        "--log",
                        str(path),
                        "--source",
                        "exec",
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
                        handle.write(
                            json.dumps(
                                {"type": terminal_event, "thread_id": "watched"}
                            )
                            + "\n"
                        )
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
            write_jsonl(path, [{"type": "turn.started", "thread_id": "watched"}])
            process = subprocess.Popen(
                [
                    sys.executable,
                    str(SCRIPT),
                    "monitor",
                    "--log",
                    str(path),
                    "--source",
                    "exec",
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
                    [{"type": "turn.completed", "thread_id": "watched"}],
                )
                replacement.replace(path)
                stdout, stderr = process.communicate(timeout=5)
            finally:
                if process.poll() is None:
                    process.kill()
                    process.wait()

        self.assertEqual(process.returncode, 0, stderr)
        self.assertEqual(json.loads(stdout)["type"], "codex_session_complete")

    def test_monitor_reports_parse_errors_with_a_terminal_event(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "events.jsonl"
            path.write_text(
                'not json\n{"type":"turn.completed","thread_id":"parsed"}\n',
                encoding="utf-8",
            )
            result = run_monitor("--log", str(path), "--source", "exec", "--once")

        notification = json.loads(result.stdout)
        self.assertEqual(notification["type"], "codex_session_complete")
        self.assertEqual(notification["parse_errors"], 1)

    def test_low_parser_confidence_stops_before_a_later_terminal_event(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "events.jsonl"
            write_jsonl(
                path,
                [
                    {"type": "future.event.one"},
                    {"type": "future.event.two"},
                ],
            )
            process = subprocess.Popen(
                [
                    sys.executable,
                    str(SCRIPT),
                    "monitor",
                    "--log",
                    str(path),
                    "--source",
                    "exec",
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
                with path.open("a", encoding="utf-8") as handle:
                    handle.write('{"type":"turn.completed","thread_id":"not-trusted"}\n')
                stdout, stderr = process.communicate(timeout=5)
            finally:
                if process.poll() is None:
                    process.kill()
                    process.wait()

        self.assertEqual(process.returncode, 2, stderr)
        notifications = [json.loads(line) for line in stdout.splitlines()]
        self.assertEqual([item["type"] for item in notifications], ["codex_session_unknown"])
        self.assertEqual(notifications[0]["compatibility"]["parse_confidence"], "low")

    def test_explicit_missing_log_is_an_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "missing-events.jsonl"
            result = run_monitor("--log", str(path), "--source", "exec", "--once")

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
            self.assertEqual(notification["path"], str(path))

    def test_invalid_lifecycle_uses_execution_mtime_fallback_with_warning(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run_dir = self.make_run(root)
            _, path = self.add_execution(
                run_dir, events=[{"type": "turn.completed", "thread_id": "fallback"}]
            )
            (run_dir / "journal.jsonl").write_text("not json\n", encoding="utf-8")

            result = run_monitor("--repo", str(root), "--once")

        notifications = [json.loads(line) for line in result.stdout.splitlines()]
        self.assertTrue(any(item["type"] == "monitor_warning" for item in notifications))
        terminal = [item for item in notifications if item["type"] == "codex_session_complete"]
        self.assertEqual(terminal[0]["path"], str(path))


if __name__ == "__main__":
    unittest.main()
