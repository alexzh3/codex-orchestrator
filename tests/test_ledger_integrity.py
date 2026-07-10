from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "codex_orch.py"
sys.path.insert(0, str(ROOT / "scripts"))

from codex_orch import read_jsonl_with_warnings  # noqa: E402


class LedgerIntegrityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self.tmp.name)
        self.run_cli("init", "--repo", str(self.repo), "--run-id", "run")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def run_cli(self, *args: str) -> subprocess.CompletedProcess[str]:
        result = subprocess.run(
            [sys.executable, str(SCRIPT), *args],
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=self.repo,
        )
        if result.returncode != 0:
            self.fail(f"command failed: {result.args}\nstdout={result.stdout}\nstderr={result.stderr}")
        return result

    def ledger_dir(self) -> Path:
        return self.repo / ".codex-orchestrator" / "runs" / "run"

    def test_malformed_ledger_line_surfaces_warning_and_valid_records_remain(self) -> None:
        verification = {
            "type": "verification",
            "recorded_at": "2026-06-29T00:00:00Z",
            "kind": "test",
            "result": "passed",
            "summary": "Valid verification survived malformed ledger line",
        }
        task = {
            "type": "task",
            "id": "task-1",
            "title": "Valid task survived malformed ledger line",
            "status": "complete",
        }
        ledger_path = self.ledger_dir() / "ledger.jsonl"
        ledger_path.write_text(
            "\n".join(
                [
                    json.dumps(verification, sort_keys=True),
                    '{"type":"verification"',
                    "",
                    json.dumps(task, sort_keys=True),
                ]
            )
            + "\n",
            encoding="utf-8",
        )

        records, diagnostics = read_jsonl_with_warnings(ledger_path)
        self.assertEqual([record["type"] for record in records], ["verification", "task"])
        self.assertEqual(len(diagnostics), 1)
        self.assertEqual(diagnostics[0]["line_no"], 2)

        status = json.loads(self.run_cli("status", "--repo", str(self.repo), "--run-id", "run").stdout)
        warnings_text = "\n".join(status["warnings"])
        self.assertEqual(status["latest_verification"]["summary"], verification["summary"])
        self.assertIn("Ledger contains 1 malformed JSON line(s).", warnings_text)
        self.assertIn("ledger.jsonl line 2", warnings_text)



if __name__ == "__main__":
    unittest.main()
