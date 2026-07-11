from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from scripts.codex_orchestrator.events import read_stream

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "codex_orch_tools.py"
FIXTURES = ROOT / "tests" / "fixtures"


def run_cli(*args: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        check=False,
        text=True,
        capture_output=True,
        cwd=ROOT,
        env={**os.environ, **(env or {})},
    )


class ToolTests(unittest.TestCase):
    def test_reader_preserves_partial_lines_and_counts_parse_errors(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "events.jsonl"
            first = '{"type":"turn.started"}\n'
            path.write_text(
                first + "not json\n[]\n" + '{"type":"turn.completed"', encoding="utf-8"
            )

            _, records, _, offset, parse_errors = read_stream(path, "exec", since_offset=0)
            self.assertEqual(
                [record.event_type for record in records],
                ["turn.started", "<invalid-json>", "<non-object>"],
            )
            self.assertEqual(parse_errors, 2)
            self.assertLess(offset, path.stat().st_size)

            with path.open("a", encoding="utf-8") as handle:
                handle.write("}\n")
            _, completed, _, next_offset, parse_errors = read_stream(
                path, "exec", since_offset=offset
            )

        self.assertEqual([record.event_type for record in completed], ["turn.completed"])
        self.assertEqual(parse_errors, 0)
        self.assertGreater(next_offset, offset)

    def test_exec_stream_completed_status(self) -> None:
        result = run_cli(
            "state",
            "exec-complete-001",
            "--source",
            "exec",
            "--file",
            str(FIXTURES / "exec_stream.jsonl"),
            "--json",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["status"], "complete")
        self.assertEqual(payload["details"]["last_agent_message"], "Implemented the scoped change.")
        self.assertEqual(payload["details"]["usage"]["output_tokens"], 45)
        self.assertEqual(payload["compatibility"]["parse_confidence"], "high")
        self.assertEqual(payload["compatibility"]["unknown_event_types"], [])

    def test_rollout_idle_status(self) -> None:
        result = run_cli(
            "state",
            "ide-idle-001",
            "--source",
            "ide",
            "--file",
            str(FIXTURES / "rollout.jsonl"),
            "--json",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["status"], "idle")
        self.assertEqual(payload["compatibility"]["parse_confidence"], "high")

    def test_failed_turn_detected(self) -> None:
        result = run_cli(
            "state",
            "exec-failed-001",
            "--source",
            "exec",
            "--file",
            str(FIXTURES / "exec_failed_stream.jsonl"),
            "--json",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["status"], "failed")

    def test_failed_rollout_signature_detected(self) -> None:
        result = run_cli(
            "state",
            "ide-failed-001",
            "--source",
            "ide",
            "--file",
            str(FIXTURES / "rollout_failed.jsonl"),
            "--json",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["status"], "failed")

    def test_later_ide_goal_supersedes_an_older_failure_message(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "rollout.jsonl"
            path.write_text(
                json.dumps(
                    {
                        "payload": {
                            "type": "agent_message",
                            "message": "FAILED old verification",
                        }
                    }
                )
                + "\n"
                + json.dumps(
                    {
                        "payload": {
                            "type": "thread_goal_updated",
                            "goal": {"status": "complete", "text": "Fixed and rechecked"},
                        }
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            result = run_cli(
                "state", "ide-latest", "--source", "ide", "--file", str(path), "--json"
            )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["status"], "complete")

    def test_ide_state_does_not_guess_from_staleness_or_message_text(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "rollout.jsonl"
            path.write_text(
                json.dumps(
                    {
                        "payload": {
                            "type": "thread_goal_updated",
                            "goal": {"status": "active", "text": "Continue the task"},
                        }
                    }
                )
                + "\n"
                + json.dumps(
                    {
                        "payload": {
                            "type": "agent_message",
                            "message": "Waiting for approval may be necessary.",
                        }
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            os.utime(path, (1, 1))
            result = run_cli(
                "state", "ide-stale", "--source", "ide", "--file", str(path), "--json"
            )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["status"], "active")

    def test_later_exec_activity_supersedes_an_older_completion(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "events.jsonl"
            path.write_text(
                '{"type":"turn.completed"}\n{"type":"turn.started"}\n',
                encoding="utf-8",
            )
            result = run_cli(
                "state", "exec-latest", "--source", "exec", "--file", str(path), "--json"
            )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["status"], "active")

    def test_unknown_format_exits_nonzero_and_low_confidence(self) -> None:
        result = run_cli(
            "state",
            "unknown-001",
            "--source",
            "ide",
            "--file",
            str(FIXTURES / "unknown_format.jsonl"),
            "--json",
        )
        self.assertNotEqual(result.returncode, 0)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["status"], "unknown")
        self.assertEqual(payload["compatibility"]["parse_confidence"], "low")
        self.assertIn("Do not infer session status", result.stderr)

    def test_tail_since_offset_emits_json_events(self) -> None:
        result = run_cli(
            "tail",
            "exec-complete-001",
            "--since-offset",
            "0",
            "--source",
            "exec",
            "--file",
            str(FIXTURES / "exec_stream.jsonl"),
            "--json",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertGreater(payload["next_offset"], payload["offset"])
        self.assertEqual(payload["events"][0]["type"], "thread.started")

    def test_tail_retries_an_unterminated_final_event(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "events.jsonl"
            complete = '{"type":"turn.started"}\n'
            path.write_text(complete + '{"type":"turn.completed"', encoding="utf-8")

            first = run_cli(
                "tail",
                "partial-event",
                "--since-offset",
                "0",
                "--source",
                "exec",
                "--file",
                str(path),
                "--json",
            )
            first_payload = json.loads(first.stdout)
            with path.open("a", encoding="utf-8") as handle:
                handle.write("}\n")
            second = run_cli(
                "tail",
                "partial-event",
                "--since-offset",
                str(first_payload["next_offset"]),
                "--source",
                "exec",
                "--file",
                str(path),
                "--json",
            )

        self.assertEqual(first.returncode, 0, first.stderr)
        self.assertEqual([event["type"] for event in first_payload["events"]], ["turn.started"])
        self.assertEqual(first_payload["next_offset"], len(complete.encode()))
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertEqual(json.loads(second.stdout)["events"][0]["type"], "turn.completed")

    def test_find_returns_the_newest_ide_rollout(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            sessions = Path(tmp) / ".codex" / "sessions" / "2026" / "07" / "11"
            sessions.mkdir(parents=True)
            older = sessions / "rollout-old-thread-123.jsonl"
            newer = sessions / "rollout-new-thread-123.jsonl"
            older.write_text("{}\n", encoding="utf-8")
            newer.write_text("{}\n", encoding="utf-8")
            os.utime(older, (1, 1))
            os.utime(newer, (2, 2))
            result = run_cli("find", "thread-123", "--json", env={"HOME": tmp})

        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["source"], "ide")
        self.assertEqual(payload["path"], str(newer))

    def test_state_dumps_event_types_for_format_diagnostics(self) -> None:
        result = run_cli(
            "state",
            "exec-complete-001",
            "--source",
            "exec",
            "--file",
            str(FIXTURES / "exec_stream.jsonl"),
            "--dump-event-types",
            "--json",
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["event_types"]["turn.completed"], 1)

    def test_state_without_event_file_still_emits_status_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            result = run_cli(
                "state",
                "missing-thread",
                "--source",
                "exec",
                "--json",
                env={"HOME": tmp_dir},
            )
        self.assertEqual(result.returncode, 0)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["status"], "idle")
        self.assertIsNone(payload["path"])

    def test_ide_state_uses_a_bounded_initial_tail(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "rollout.jsonl"
            terminal = json.dumps(
                {
                    "payload": {
                        "type": "thread_goal_updated",
                        "goal": {"status": "complete", "text": "Finished"},
                    }
                }
            )
            path.write_text("x" * 600_000 + "\n" + terminal + "\n", encoding="utf-8")
            result = run_cli(
                "state", "large-ide", "--source", "ide", "--file", str(path), "--json"
            )

        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertGreater(payload["offset"], 0)
        self.assertEqual(payload["status"], "complete")


if __name__ == "__main__":
    unittest.main()
