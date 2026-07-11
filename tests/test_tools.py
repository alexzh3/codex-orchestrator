from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from scripts.codex_orchestrator.events import IDE_HISTORY_LIMIT_BYTES

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
    def test_state_ignores_an_incomplete_final_event(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "events.jsonl"
            path.write_text(
                '{"type":"turn.started"}\n{"type":"turn.completed"',
                encoding="utf-8",
            )
            partial = run_cli(
                "state", "partial", "--source", "exec", "--file", str(path), "--json"
            )
            with path.open("a", encoding="utf-8") as handle:
                handle.write("}\n")
            completed = run_cli(
                "state", "complete", "--source", "exec", "--file", str(path), "--json"
            )

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
            result = run_cli(
                "state", "unterminated", "--source", "exec", "--file", str(path), "--json"
            )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["status"], "complete")

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

    def test_exec_reconnect_is_ignored_but_an_error_fails_the_session(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            reconnect_path = Path(tmp) / "reconnect.jsonl"
            error_path = Path(tmp) / "error.jsonl"
            reconnect_path.write_text(
                '{"type":"thread.started"}\n'
                '{"type":"error","message":"Reconnecting to stream"}\n',
                encoding="utf-8",
            )
            error_path.write_text(
                '{"type":"error","message":"authentication failed"}\n',
                encoding="utf-8",
            )
            reconnect = run_cli(
                "state", "reconnect", "--source", "exec", "--file", str(reconnect_path), "--json"
            )
            failed = run_cli(
                "state", "error", "--source", "exec", "--file", str(error_path), "--json"
            )

        self.assertEqual(json.loads(reconnect.stdout)["status"], "idle")
        failed_payload = json.loads(failed.stdout)
        self.assertEqual(failed_payload["status"], "failed")
        self.assertEqual(failed_payload["details"]["error"], "authentication failed")

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

    def test_ide_goal_status_controls_blocked_and_failed_sessions(self) -> None:
        cases = (("blocked", "awaiting-approval"), ("failed", "failed"))
        for goal_status, expected_status in cases:
            with self.subTest(goal_status=goal_status), tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / "rollout.jsonl"
                path.write_text(
                    json.dumps(
                        {
                            "payload": {
                                "type": "thread_goal_updated",
                                "goal": {"status": goal_status, "text": "Current task"},
                            }
                        }
                    )
                    + "\n",
                    encoding="utf-8",
                )
                result = run_cli(
                    "state", "ide-goal", "--source", "ide", "--file", str(path), "--json"
                )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout)["status"], expected_status)

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

    def test_ide_function_call_output_does_not_signal_session_failure(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "rollout.jsonl"
            write_records = [
                {
                    "payload": {
                        "type": "thread_goal_updated",
                        "goal": {"status": "active", "text": "Continue the task"},
                    }
                },
                {
                    "payload": {
                        "type": "function_call",
                        "name": "shell",
                        "arguments": {"command": "printf 'FAILED intermediate check'"},
                    }
                },
            ]
            path.write_text(
                "".join(json.dumps(record) + "\n" for record in write_records),
                encoding="utf-8",
            )
            result = run_cli(
                "state", "ide-tool-output", "--source", "ide", "--file", str(path), "--json"
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
            human = run_cli("find", "thread-123", env={"HOME": tmp})
            missing = run_cli("find", "missing-thread", "--json", env={"HOME": tmp})

        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["source"], "ide")
        self.assertEqual(payload["path"], str(newer))
        self.assertEqual(human.stdout.strip(), str(newer))
        self.assertEqual(missing.returncode, 1)
        self.assertIsNone(json.loads(missing.stdout)["path"])

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

    def test_ide_state_uses_bounded_recent_history(self) -> None:
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
        self.assertEqual(payload["status"], "complete")

    def test_bounded_ide_read_is_safe_at_a_multibyte_boundary(self) -> None:
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
            raw = b""
            for suffix in ("", "x"):
                first = json.dumps(
                    {
                        "payload": {
                            "type": "agent_message",
                            "message": "é" * 300_000 + suffix,
                        }
                    },
                    ensure_ascii=False,
                )
                raw = (first + "\n" + terminal + "\n").encode("utf-8")
                if raw[len(raw) - IDE_HISTORY_LIMIT_BYTES] & 0b1100_0000 == 0b1000_0000:
                    break
            self.assertEqual(
                raw[len(raw) - IDE_HISTORY_LIMIT_BYTES] & 0b1100_0000,
                0b1000_0000,
            )
            path.write_bytes(raw)
            result = run_cli(
                "state", "utf8-boundary", "--source", "ide", "--file", str(path), "--json"
            )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["status"], "complete")

    def test_bounded_ide_history_without_lifecycle_is_low_confidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "rollout.jsonl"
            path.write_text(
                json.dumps(
                    {
                        "payload": {
                            "type": "agent_message",
                            "message": "x" * (IDE_HISTORY_LIMIT_BYTES + 1),
                        }
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            result = run_cli(
                "state", "truncated-ide", "--source", "ide", "--file", str(path), "--json"
            )

        self.assertEqual(result.returncode, 2)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["status"], "unknown")
        self.assertEqual(payload["compatibility"]["parse_confidence"], "low")
        self.assertIn(
            "bounded IDE history contains no lifecycle event",
            payload["compatibility"]["warnings"],
        )


if __name__ == "__main__":
    unittest.main()
