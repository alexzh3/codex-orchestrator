from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "codex_orch.py"


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

    def test_init_creates_ledger(self) -> None:
        result = self.run_cli("init", "--run-id", "run", "--repo", str(self.repo))
        payload = json.loads(result.stdout)

        self.assertTrue(payload["ok"])
        self.assertTrue((self.ledger_dir() / "state.json").is_file())
        self.assertTrue((self.ledger_dir() / "ledger.jsonl").is_file())
        self.assertTrue((self.ledger_dir() / "report.md").is_file())
        self.assertFalse((self.ledger_dir() / "events.jsonl").exists())
        self.assertFalse((self.ledger_dir() / "tasks.json").exists())
        self.assertFalse((self.ledger_dir() / "verification.jsonl").exists())
        self.assertFalse((self.ledger_dir() / "consensus.md").exists())
        self.assertFalse((self.ledger_dir() / "final-report.md").exists())

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

    def test_report_records_missing_and_present_evidence(self) -> None:
        self.init_run()
        self.run_cli("report", "--run-id", "run")
        report = (self.ledger_dir() / "report.md").read_text(encoding="utf-8")
        self.assertIn("No verification evidence recorded.", report)

        self.run_cli(
            "add-verification",
            "--run-id",
            "run",
            "--kind",
            "manual_review",
            "--result",
            "needs_human_review",
            "--summary",
            "Parser warning requires manual inspection",
        )
        self.run_cli("report", "--run-id", "run")
        report = (self.ledger_dir() / "report.md").read_text(encoding="utf-8")
        self.assertIn("Parser warning requires manual inspection", report)
        self.assertIn("No acceptance decision recorded", report)


if __name__ == "__main__":
    unittest.main()
