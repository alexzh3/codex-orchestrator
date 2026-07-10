from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "codex_orch_parse.py"
PARSE_MODULE = ROOT / "scripts" / "codex_orchestrator" / "parse.py"
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


class ParseCliTests(unittest.TestCase):
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

    def test_find_accepts_common_parser_flags(self) -> None:
        result = run_cli(
            "find",
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
        self.assertEqual(payload["source"], "exec")
        self.assertEqual(payload["event_types"]["turn.completed"], 1)

    def test_find_auto_detects_an_explicit_exec_stream(self) -> None:
        result = run_cli(
            "find",
            "exec-complete-001",
            "--file",
            str(FIXTURES / "exec_stream.jsonl"),
            "--dump-event-types",
            "--json",
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["source"], "exec")

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

    def test_ide_reader_uses_seek_tail_pattern(self) -> None:
        source = PARSE_MODULE.read_text(encoding="utf-8")
        self.assertIn("seek(max(0, size - TAIL_LIMIT_BYTES))", source)
        self.assertNotIn(".readlines(", source)
        self.assertNotIn(".read()", source)


if __name__ == "__main__":
    unittest.main()
