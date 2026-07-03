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
SCRIPT = ROOT / "scripts" / "codex_orch.py"
TEST_COMMAND = "python3 -m unittest tests.test_findings_gate -v"


class FindingsGateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self.tmp.name)
        self.run_cli("init", "--repo", str(self.repo), "--run-id", "run")
        self.add_final_review()

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

    def ledger_dir(self) -> Path:
        return self.repo / ".codex-orchestrator" / "runs" / "run"

    def ledger_path(self) -> Path:
        return self.ledger_dir() / "ledger.jsonl"

    def report_path(self) -> Path:
        return self.ledger_dir() / "report.md"

    def append_event(self, event: dict[str, object]) -> None:
        self.run_cli("append-event", "--repo", str(self.repo), "--run-id", "run", json.dumps(event))

    def refresh_report_mtime(self) -> None:
        future = time.time() + 60
        os.utime(self.report_path(), (future, future))

    def add_final_review(self) -> None:
        self.append_event(
            {
                "type": "verification",
                "kind": "manual_review",
                "result": "passed",
                "scope": "global",
                "summary": "No blocking findings in the run-wide final review.",
            }
        )

    def add_blocking_review(self, **finding_fields: object) -> None:
        finding: dict[str, object] = {
            "id": "F1",
            "claim": "The patch can fail at runtime.",
            "severity": "P1",
            "repro_command": TEST_COMMAND,
        }
        finding.update(finding_fields)
        if finding.get("repro_command") is None:
            finding.pop("repro_command", None)
        self.append_event(
            {
                "type": "review",
                "task_id": "task-a",
                "reviewer": "claude",
                "kind": "diff",
                "result": "failed",
                "summary": "Blocking review findings.",
                "blocking_findings": [finding],
            }
        )

    def add_repro_verification(self, **fields: object) -> None:
        record: dict[str, object] = {
            "type": "verification",
            "id": "V1",
            "recorded_at": "2026-06-29T08:05:00Z",
            "kind": "test",
            "result": "passed",
            "summary": "Repro verification passed.",
            "command": TEST_COMMAND,
            "finding_id": "F1",
        }
        record.update(fields)
        self.append_event(record)

    def run_gate(self, *, check: bool = True) -> dict[str, object]:
        self.refresh_report_mtime()
        result = self.run_cli("gate", "--repo", str(self.repo), "--run-id", "run", check=check)
        return json.loads(result.stdout)

    def run_doctor(self, *, check: bool = True) -> dict[str, object]:
        self.refresh_report_mtime()
        result = self.run_cli("doctor", "--repo", str(self.repo), "--run-id", "run", check=check)
        return json.loads(result.stdout)

    def test_gate_blocks_p1_finding_without_repro_evidence(self) -> None:
        self.add_blocking_review()

        payload = self.run_gate(check=False)

        self.assertFalse(payload["ok"])
        self.assertTrue(any(item.startswith("pending-repro:") for item in payload["blocking"]))

    def test_gate_blocks_insufficient_repro_attempts(self) -> None:
        self.add_blocking_review(min_repro_attempts=3)
        self.add_repro_verification(attempt_count=2)

        payload = self.run_gate(check=False)

        self.assertFalse(payload["ok"])
        self.assertTrue(any("has 2 passing repro attempt(s), needs 3" in item for item in payload["blocking"]))

    def test_unrelated_passing_verification_does_not_satisfy_repro(self) -> None:
        self.add_blocking_review()
        self.add_repro_verification(command="true")

        payload = self.run_gate(check=False)

        self.assertFalse(payload["ok"])
        self.assertTrue(any(item.startswith("pending-repro:") for item in payload["blocking"]))

    def test_pre_review_repro_run_does_not_satisfy(self) -> None:
        self.add_repro_verification()
        self.add_blocking_review()

        payload = self.run_gate(check=False)

        self.assertFalse(payload["ok"])
        self.assertTrue(any(item.startswith("pending-repro:") for item in payload["blocking"]))

    def test_gate_passes_when_repro_attempts_satisfied(self) -> None:
        self.add_blocking_review(min_repro_attempts=3)
        self.add_repro_verification(attempt_count=3)

        payload = self.run_gate()

        self.assertTrue(payload["ok"])
        self.assertEqual(payload["blocking"], [])

    def test_failed_repro_verification_blocks_via_unresolved_verification_not_pending_repro(self) -> None:
        self.add_blocking_review()
        self.add_repro_verification(result="failed", summary="Repro verification failed.")

        payload = self.run_gate(check=False)

        self.assertFalse(payload["ok"])
        self.assertEqual(len(payload["blocking"]), 1)
        self.assertTrue(payload["blocking"][0].startswith("unresolved-verification:"))

    def test_p2_finding_never_blocks(self) -> None:
        self.add_blocking_review(severity="P2")

        payload = self.run_gate()

        self.assertTrue(payload["ok"])
        self.assertEqual(payload["blocking"], [])

    def test_finding_without_repro_command_warns_and_doctor_flags(self) -> None:
        self.add_blocking_review(repro_command=None)

        payload = self.run_gate()

        self.assertTrue(payload["ok"])
        self.assertEqual(payload["blocking"], [])
        self.assertTrue(any(item.startswith("finding-no-repro-command:") for item in payload["warnings"]))

        doctor_payload = self.run_doctor(check=False)
        self.assertFalse(doctor_payload["ok"])
        self.assertTrue(any("finding-missing-repro: blocking finding 'F1'" in item for item in doctor_payload["issues"]))

    def test_accepted_risk_consensus_clears_finding_by_ref(self) -> None:
        self.add_blocking_review()
        self.append_event(
            {
                "type": "consensus",
                "finding": "The patch can fail at runtime.",
                "outcome": "consensus",
                "resolution": "Accepted as a tracked risk.",
                "resolution_basis": "accepted_risk",
                "requires_user": False,
                "evidence": ["risk reviewed"],
                "clears": ["finding:F1"],
            }
        )

        payload = self.run_gate()

        self.assertTrue(payload["ok"])
        self.assertEqual(payload["blocking"], [])

    def test_refiled_finding_blocks_after_earlier_clear(self) -> None:
        self.add_blocking_review()
        self.append_event(
            {
                "type": "consensus",
                "finding": "The patch can fail at runtime.",
                "outcome": "consensus",
                "resolution": "Accepted as a tracked risk.",
                "resolution_basis": "accepted_risk",
                "requires_user": False,
                "evidence": ["risk reviewed"],
                "clears": ["finding:F1"],
            }
        )
        self.add_blocking_review()

        payload = self.run_gate(check=False)

        self.assertFalse(payload["ok"])
        self.assertTrue(any(item.startswith("pending-repro:") for item in payload["blocking"]))

    def test_plain_consensus_does_not_clear_finding(self) -> None:
        self.add_blocking_review()
        self.append_event(
            {
                "type": "consensus",
                "finding": "The patch can fail at runtime.",
                "outcome": "consensus",
                "resolution": "Text mentions F1 but has no clear ref.",
                "requires_user": False,
                "evidence": ["review"],
            }
        )

        payload = self.run_gate(check=False)

        self.assertFalse(payload["ok"])
        self.assertTrue(any(item.startswith("pending-repro:") for item in payload["blocking"]))


if __name__ == "__main__":
    unittest.main()
