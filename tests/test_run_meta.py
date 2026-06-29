from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "codex_orch.py"


class RunMetaTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self.tmp.name)
        plugin_dir = self.repo / ".claude-plugin"
        plugin_dir.mkdir()
        (plugin_dir / "plugin.json").write_text(
            json.dumps({"name": "codex-orchestrator", "version": "9.9.9"}) + "\n",
            encoding="utf-8",
        )

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

    def ledger_records(self) -> list[dict[str, object]]:
        return [
            json.loads(line)
            for line in (self.ledger_dir() / "ledger.jsonl").read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]

    def test_ensure_run_writes_one_run_meta_and_report_reproducibility(self) -> None:
        first = json.loads(
            self.run_cli(
                "ensure-run",
                "--repo",
                str(self.repo),
                "--run-id",
                "run",
                "--plugin-ref",
                "plugin-sha-a",
                "--benchmark-suite",
                "suite-a",
                "--benchmark-case-id",
                "case-a",
            ).stdout
        )
        self.assertTrue(first["ok"])
        self.assertEqual(first["run_meta_action"], "created")
        self.assertTrue((self.ledger_dir() / "state.json").is_file())

        second = json.loads(
            self.run_cli(
                "ensure-run",
                "--repo",
                str(self.repo),
                "--run-id",
                "run",
                "--plugin-ref",
                "plugin-sha-b",
                "--benchmark-suite",
                "suite-a",
                "--benchmark-case-id",
                "case-b",
            ).stdout
        )
        self.assertEqual(second["run_meta_action"], "updated")

        run_meta_records = [record for record in self.ledger_records() if record.get("type") == "run_meta"]
        self.assertEqual(len(run_meta_records), 1)
        run_meta = run_meta_records[0]
        self.assertEqual(run_meta["run_id"], "run")
        self.assertEqual(run_meta["plugin_version"], "9.9.9")
        self.assertEqual(run_meta["plugin_git_sha"], "plugin-sha-b")
        self.assertEqual(run_meta["protocol_version"], "1.0")
        self.assertEqual(run_meta["schema_version"], "1.0")
        self.assertEqual(run_meta["benchmark_suite"], "suite-a")
        self.assertEqual(run_meta["benchmark_case_id"], "case-b")
        self.assertIsInstance(run_meta["config"], dict)

        self.run_cli("report", "--repo", str(self.repo), "--run-id", "run")
        report = (self.ledger_dir() / "report.md").read_text(encoding="utf-8")
        self.assertIn("## Reproducibility", report)
        self.assertIn("- Plugin Version: `9.9.9`", report)
        self.assertIn("- Plugin Git SHA: `plugin-sha-b`", report)
        self.assertIn("- Protocol Version: `1.0`", report)
        self.assertIn("- Schema Version: `1.0`", report)
        self.assertIn("- Benchmark Suite: `suite-a`", report)
        self.assertIn("- Benchmark Case: `case-b`", report)
        self.assertIn("- Report Completeness: 0.15", report)


if __name__ == "__main__":
    unittest.main()
