from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import tracemalloc
import unittest
from pathlib import Path

from scripts.codex_orchestrator.events import summarize_stream

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "codex_orch_tools.py"
FIXTURES = ROOT / "tests" / "fixtures"


def run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        check=False,
        text=True,
        capture_output=True,
        cwd=ROOT,
    )


class ToolTests(unittest.TestCase):
    def test_state_ignores_an_incomplete_final_event(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "events.jsonl"
            path.write_text(
                '{"type":"turn.started"}\n{"type":"turn.completed"',
                encoding="utf-8",
            )
            partial = run_cli("state", "partial", "--file", str(path), "--json")
            with path.open("a", encoding="utf-8") as handle:
                handle.write("}\n")
            completed = run_cli("state", "complete", "--file", str(path), "--json")

        self.assertEqual(partial.returncode, 0, partial.stderr)
        self.assertEqual(json.loads(partial.stdout)["status"], "active")
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(json.loads(completed.stdout)["status"], "complete")

    def test_state_accepts_a_complete_unterminated_final_event(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "events.jsonl"
            path.write_text(
                '{"type":"turn.started"}\n{"type":"turn.completed"}',
                encoding="utf-8",
            )
            result = run_cli("state", "unterminated", "--file", str(path), "--json")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["status"], "complete")

    def test_partial_first_event_reports_starting_without_low_confidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "partial.jsonl"
            path.write_text('{"type":"thread.started"', encoding="utf-8")
            result = run_cli("state", "partial", "--file", str(path), "--json")

        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["status"], "starting")
        self.assertEqual(payload["compatibility"]["parse_confidence"], "high")

    def test_exec_stream_completed_status(self) -> None:
        result = run_cli(
            "state",
            "requested-id",
            "--file",
            str(FIXTURES / "exec_stream.jsonl"),
            "--json",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["thread_id"], "exec-complete-001")
        self.assertEqual(payload["status"], "complete")
        self.assertEqual(payload["details"]["last_agent_message"], "Implemented the scoped change.")
        self.assertEqual(payload["details"]["usage"]["output_tokens"], 45)
        self.assertEqual(payload["compatibility"]["parse_confidence"], "high")
        self.assertEqual(payload["compatibility"]["unknown_event_types"], [])

    def test_failed_turn_detected(self) -> None:
        result = run_cli(
            "state", "failed", "--file", str(FIXTURES / "exec_failed_stream.jsonl"), "--json"
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["status"], "failed")

    def test_reconnect_is_ignored_but_an_error_fails_the_agent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            reconnect_path = Path(tmp) / "reconnect.jsonl"
            error_path = Path(tmp) / "error.jsonl"
            reconnect_path.write_text(
                '{"type":"thread.started","thread_id":"native"}\n'
                '{"type":"error","message":"Reconnecting to stream"}\n',
                encoding="utf-8",
            )
            error_path.write_text(
                '{"type":"error","message":"authentication failed"}\n',
                encoding="utf-8",
            )
            reconnect = run_cli("state", "reconnect", "--file", str(reconnect_path), "--json")
            failed = run_cli("state", "error", "--file", str(error_path), "--json")

        self.assertEqual(json.loads(reconnect.stdout)["status"], "starting")
        failed_payload = json.loads(failed.stdout)
        self.assertEqual(failed_payload["status"], "failed")
        self.assertEqual(failed_payload["details"]["error"], "authentication failed")

    def test_later_exec_activity_supersedes_an_older_completion(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "events.jsonl"
            path.write_text(
                '{"type":"turn.completed"}\n{"type":"turn.started"}\n',
                encoding="utf-8",
            )
            result = run_cli("state", "latest", "--file", str(path), "--json")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["status"], "active")

    def test_recognized_pre_turn_events_report_starting(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "starting.jsonl"
            path.write_text(
                '{"type":"thread.started","thread_id":"native"}\n',
                encoding="utf-8",
            )
            result = run_cli("state", "starting", "--file", str(path), "--json")

        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["status"], "starting")
        self.assertEqual(payload["compatibility"]["parse_confidence"], "high")

    def test_unknown_format_exits_nonzero_and_low_confidence(self) -> None:
        result = run_cli(
            "state", "unknown", "--file", str(FIXTURES / "unknown_format.jsonl"), "--json"
        )
        self.assertEqual(result.returncode, 2)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["status"], "unknown")
        self.assertEqual(payload["compatibility"]["parse_confidence"], "low")
        self.assertIn("Do not infer agent status", result.stderr)

    def test_state_dumps_event_types_for_format_diagnostics(self) -> None:
        result = run_cli(
            "state",
            "complete",
            "--file",
            str(FIXTURES / "exec_stream.jsonl"),
            "--dump-event-types",
            "--json",
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["event_types"]["turn.completed"], 1)

    def test_state_requires_an_existing_event_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            missing = Path(tmp) / "missing.jsonl"
            cases = (
                run_cli("state", "missing", "--file", str(missing), "--json"),
                run_cli("state", "missing", "--json"),
            )

        for result in cases:
            with self.subTest(stdout=result.stdout):
                self.assertEqual(result.returncode, 1, result.stderr)
                payload = json.loads(result.stdout)
                self.assertEqual(payload["type"], "state_error")
                self.assertIn("does not exist", payload["message"])

    def test_stream_summary_memory_does_not_scale_with_event_count(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "events.jsonl"
            path.write_bytes(b'{"type":"item.started"}\n' * 50_000)
            tracemalloc.start()
            summary = summarize_stream(path)
            _, peak = tracemalloc.get_traced_memory()
            tracemalloc.stop()

        self.assertEqual(summary.event_count, 50_000)
        self.assertLess(peak, 2_000_000)


if __name__ == "__main__":
    unittest.main()
