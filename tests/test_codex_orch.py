from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "codex_orch.py"

def git_head(path: Path) -> str | None:
    result = subprocess.run(
        ["git", "-C", str(path), "rev-parse", "HEAD"],
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


class CodexOrchCliTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self.tmp.name)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def run_cli(self, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
        result = subprocess.run(
            [sys.executable, str(SCRIPT), *args],
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=self.repo,
        )
        if check and result.returncode != 0:
            self.fail(f"command failed: {result.args}\nstdout={result.stdout}\nstderr={result.stderr}")
        return result

    def ledger_dir(self, run_id: str = "run") -> Path:
        return self.repo / ".codex-orchestrator" / "runs" / run_id

    def init_run(self) -> None:
        self.run_cli("init", "--run-id", "run", "--repo", str(self.repo))

    def init_target_git_repo(self) -> str:
        subprocess.run(["git", "init"], check=True, cwd=self.repo, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        subprocess.run(
            ["git", "config", "user.email", "test@example.com"],
            check=True,
            cwd=self.repo,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        subprocess.run(
            ["git", "config", "user.name", "Test User"],
            check=True,
            cwd=self.repo,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        (self.repo / "README.md").write_text("target repo\n", encoding="utf-8")
        subprocess.run(["git", "add", "README.md"], check=True, cwd=self.repo, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        subprocess.run(
            ["git", "commit", "-m", "initial target commit"],
            check=True,
            cwd=self.repo,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        head = git_head(self.repo)
        self.assertIsNotNone(head)
        return str(head)

    def test_init_creates_ledger(self) -> None:
        result = self.run_cli("init", "--run-id", "run", "--repo", str(self.repo))
        payload = json.loads(result.stdout)

        self.assertTrue(payload["ok"])
        self.assertTrue((self.ledger_dir() / "state.json").is_file())
        self.assertTrue((self.ledger_dir() / "ledger.jsonl").is_file())
        self.assertTrue((self.ledger_dir() / "report.md").is_file())
        self.assertTrue((self.ledger_dir() / "prompts").is_dir())
        self.assertTrue((self.ledger_dir() / "logs").is_dir())
        self.assertTrue((self.ledger_dir() / "artifacts").is_dir())
        self.assertTrue(payload["created_or_replaced"]["prompts/"])
        self.assertTrue(payload["created_or_replaced"]["logs/"])
        self.assertTrue(payload["created_or_replaced"]["artifacts/"])
        report = (self.ledger_dir() / "report.md").read_text(encoding="utf-8")
        self.assertEqual(report, "")
        state = json.loads((self.ledger_dir() / "state.json").read_text(encoding="utf-8"))
        self.assertNotIn("verification_policy", state)
        self.assertFalse((self.ledger_dir() / "events.jsonl").exists())
        self.assertFalse((self.ledger_dir() / "tasks.json").exists())
        self.assertFalse((self.ledger_dir() / "verification.jsonl").exists())
        self.assertFalse((self.ledger_dir() / "consensus.md").exists())
        self.assertFalse((self.ledger_dir() / "final-report.md").exists())

    def test_report_is_not_a_python_cli_command(self) -> None:
        self.init_run()

        result = self.run_cli("report", "--run-id", "run", check=False)

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("invalid choice", result.stderr)

    def test_add_verification_and_status(self) -> None:
        self.init_run()
        self.run_cli(
            "add-verification",
            "--run-id",
            "run",
            "--kind",
            "test",
            "--command",
            "python3 -m unittest discover -s tests -v",
            "--exit-code",
            "0",
            "--result",
            "passed",
            "--summary",
            "Unit tests passed",
        )

        records = [
            json.loads(line)
            for line in (self.ledger_dir() / "ledger.jsonl").read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        self.assertEqual(records[0]["type"], "verification")
        self.assertEqual(records[0]["kind"], "test")
        self.assertEqual(records[0]["result"], "passed")

        status = json.loads(self.run_cli("status", "--run-id", "run").stdout)
        self.assertEqual(status["latest_verification"]["summary"], "Unit tests passed")
        self.assertIn("recommended_next_action", status)

    def test_append_event_writes_typed_ledger_record(self) -> None:
        self.init_run()
        result = subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                "append-event",
                "--run-id",
                "run",
                '{"summary":"smoke"}',
            ],
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=self.repo,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertTrue(payload["ok"])
        self.assertEqual(Path(payload["ledger_path"]).name, "ledger.jsonl")
        records = [
            json.loads(line)
            for line in (self.ledger_dir() / "ledger.jsonl").read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        self.assertEqual(records[0]["type"], "event")
        self.assertEqual(records[0]["summary"], "smoke")
        self.assertIn("recorded_at", records[0])

    def test_append_event_rejects_incomplete_consensus_record(self) -> None:
        self.init_run()
        result = subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                "append-event",
                "--run-id",
                "run",
                json.dumps({"type": "consensus", "finding": "Missing outcome"}),
            ],
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=self.repo,
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("consensus event missing required field", result.stderr)

    def test_append_event_rejects_invalid_typed_records(self) -> None:
        self.init_run()
        cases = [
            (
                {
                    "type": "verification",
                    "kind": "not-a-kind",
                    "result": "passed",
                    "summary": "Bad verification kind",
                },
                "verification kind must be one of",
            ),
            (
                {
                    "type": "task",
                    "id": "task-1",
                    "title": "Bad task status",
                    "status": "resolved",
                },
                "task status must be one of",
            ),
            (
                {
                    "type": "consensus",
                    "finding": "Bad status",
                    "outcome": "consensus",
                    "resolution": "Invalid legacy status should not pass.",
                    "status": "not-a-status",
                    "evidence": ["validation"],
                },
                "consensus status must be one of",
            ),
        ]
        for event, message in cases:
            with self.subTest(event=event):
                result = subprocess.run(
                    [
                        sys.executable,
                        str(SCRIPT),
                        "append-event",
                        "--run-id",
                        "run",
                        json.dumps(event),
                    ],
                    check=False,
                    text=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    cwd=self.repo,
                )

                self.assertNotEqual(result.returncode, 0)
                self.assertIn(message, result.stderr)

    def test_benchmark_output_uses_ledger_metrics_without_report_score(self) -> None:
        self.init_run()
        self.run_cli(
            "append-event",
            "--run-id",
            "run",
            json.dumps(
                {
                    "type": "task",
                    "id": "task-1",
                    "title": "Implement benchmark result output",
                    "status": "complete",
                }
            ),
        )
        self.run_cli(
            "add-verification",
            "--run-id",
            "run",
            "--kind",
            "test",
            "--result",
            "passed",
            "--summary",
            "Unit tests passed",
            "--artifact",
            "prompts/test.md",
            "--artifact",
            "logs/test.jsonl",
        )
        self.run_cli(
            "add-verification",
            "--run-id",
            "run",
            "--kind",
            "manual_review",
            "--result",
            "passed",
            "--summary",
            "Final review passed",
        )

        self.run_cli(
            "benchmark",
            "--run-id",
            "run",
            "--suite",
            "suite-a",
            "--case-id",
            "case-1",
            "--plugin-ref",
            "plugin-ref",
            "--passed",
            "true",
        )
        benchmark = json.loads((self.ledger_dir() / "benchmark.json").read_text(encoding="utf-8"))

        self.assertEqual(benchmark["suite"], "suite-a")
        self.assertEqual(benchmark["case_id"], "case-1")
        self.assertEqual(benchmark["plugin_ref"], "plugin-ref")
        self.assertIsNone(benchmark["repo_commit"])
        self.assertIs(benchmark["passed"], True)
        self.assertEqual(benchmark["codex_sessions"], 0)
        self.assertEqual(benchmark["codex_reviews"], 1)
        self.assertIs(benchmark["prompt_log_pairs_complete"], True)
        self.assertEqual(benchmark["ledger_errors"], 0)
        self.assertNotIn("report_score", benchmark)

    def test_benchmark_plugin_ref_does_not_fall_back_to_target_repo_commit(self) -> None:
        target_head = self.init_target_git_repo()
        self.init_run()

        self.run_cli("benchmark", "--run-id", "run", "--suite", "suite-a", "--case-id", "case-1")
        benchmark = json.loads((self.ledger_dir() / "benchmark.json").read_text(encoding="utf-8"))

        self.assertEqual(benchmark["repo_commit"], target_head)
        self.assertEqual(benchmark["plugin_ref"], git_head(ROOT))
        self.assertNotEqual(benchmark["plugin_ref"], target_head)

    def test_benchmark_passed_null_overrides_gate_result(self) -> None:
        self.init_run()
        self.run_cli(
            "append-event",
            "--run-id",
            "run",
            json.dumps({"type": "gate_result", "passed": True}),
        )

        self.run_cli(
            "benchmark",
            "--run-id",
            "run",
            "--suite",
            "suite-a",
            "--case-id",
            "case-1",
            "--passed",
            "null",
        )
        benchmark = json.loads((self.ledger_dir() / "benchmark.json").read_text(encoding="utf-8"))

        self.assertIs(benchmark["gate_passed"], True)
        self.assertIsNone(benchmark["passed"])

if __name__ == "__main__":
    unittest.main()
