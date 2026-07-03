from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "codex_orch.py"


class EvidenceContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self.tmp.name)
        self.run_cli("init", "--repo", str(self.repo), "--run-id", "run")

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

    def ledger_path(self) -> Path:
        return self.repo / ".codex-orchestrator" / "runs" / "run" / "ledger.jsonl"

    def ledger_records(self) -> list[dict[str, object]]:
        records: list[dict[str, object]] = []
        for line in self.ledger_path().read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            record = json.loads(line)
            if isinstance(record, dict):
                records.append(record)
        return records

    def append_event(
        self,
        event: dict[str, object],
        *,
        check: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        return self.run_cli(
            "append-event",
            "--repo",
            str(self.repo),
            "--run-id",
            "run",
            json.dumps(event),
            check=check,
        )

    def add_verification(
        self,
        *,
        summary: str = "Verification passed.",
        command: str | None = "python3 -m unittest discover -s tests -v",
        extra_args: list[str] | None = None,
        check: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        args = [
            "add-verification",
            "--repo",
            str(self.repo),
            "--run-id",
            "run",
            "--kind",
            "test",
            "--result",
            "passed",
            "--summary",
            summary,
        ]
        if command is not None:
            args.extend(["--command", command])
        if extra_args:
            args.extend(extra_args)
        return self.run_cli(*args, check=check)

    def test_add_verification_auto_generates_id_and_command_hash(self) -> None:
        command = "python3 -m unittest discover -s tests -v"

        result = self.add_verification(command=command)
        payload = json.loads(result.stdout)
        record = self.ledger_records()[-1]

        expected_hash = "sha256:" + hashlib.sha256(command.encode("utf-8")).hexdigest()
        self.assertEqual(record["id"], "V1")
        self.assertEqual(record["command_hash"], expected_hash)
        self.assertEqual(payload["verification"]["id"], "V1")

    def test_command_hash_does_not_collapse_quoted_whitespace(self) -> None:
        for command in ('echo "a  b"', 'echo "a b"', "cmd\n", "cmd"):
            self.add_verification(command=command)

        records = self.ledger_records()
        self.assertNotEqual(records[0]["command_hash"], records[1]["command_hash"])
        self.assertEqual(records[2]["command_hash"], records[3]["command_hash"])

    def test_add_verification_id_collision_bumps_counter(self) -> None:
        self.append_event(
            {
                "type": "verification",
                "id": "V2",
                "kind": "test",
                "result": "passed",
                "summary": "Preexisting verification.",
            }
        )

        self.add_verification(command=None)
        self.add_verification(command=None)

        ids = [record.get("id") for record in self.ledger_records() if record.get("type") == "verification"]
        self.assertEqual(ids, ["V2", "V1", "V3"])

    def test_add_verification_explicit_duplicate_id_rejected(self) -> None:
        self.add_verification(command=None, extra_args=["--id", "V1"])
        before = self.ledger_records()

        result = self.add_verification(command=None, extra_args=["--id", "V1"], check=False)

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("ERROR: verification id already exists: V1", result.stderr)
        self.assertEqual(self.ledger_records(), before)

    def test_add_verification_respects_new_flags(self) -> None:
        self.add_verification(
            command=None,
            extra_args=["--finding-id", "F1", "--acceptance-test", "--attempt-count", "3"],
        )
        record = self.ledger_records()[-1]

        self.assertEqual(record["finding_id"], "F1")
        self.assertTrue(record["acceptance_test"])
        self.assertEqual(record["attempt_count"], 3)

        result = self.add_verification(command=None, extra_args=["--attempt-count", "0"], check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("value must be an integer >= 1", result.stderr)

    def test_add_verification_now_validates(self) -> None:
        result = self.add_verification(summary="", command=None, check=False)

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("ERROR: verification field summary must be a non-empty string", result.stderr)

    def test_append_event_rejects_malformed_command_hash(self) -> None:
        result = self.append_event(
            {
                "type": "verification",
                "kind": "test",
                "result": "passed",
                "summary": "Bad hash.",
                "command_hash": "sha256:short",
            },
            check=False,
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("ERROR: verification field command_hash must be sha256:<64 hex digits>", result.stderr)

    def test_append_event_rejects_empty_verification_ref_ids(self) -> None:
        for field in ("id", "finding_id"):
            with self.subTest(field=field):
                event = {
                    "type": "verification",
                    "kind": "test",
                    "result": "passed",
                    "summary": "Empty id.",
                    field: "",
                }
                result = self.append_event(event, check=False)

                self.assertNotEqual(result.returncode, 0)
                self.assertIn(
                    f"ERROR: verification field {field} must be a non-empty string",
                    result.stderr,
                )

    def test_append_event_accepts_consensus_with_basis_and_refs(self) -> None:
        self.append_event(
            {
                "type": "consensus",
                "finding": "Flaky check reproduced.",
                "outcome": "consensus",
                "resolution": "Rerun passed.",
                "resolution_basis": "rerun_passed",
                "evidence": ["rerun output"],
                "clears": ["finding:F1"],
                "evidence_refs": ["verification:V1"],
            }
        )

        record = self.ledger_records()[-1]
        self.assertEqual(record["resolution_basis"], "rerun_passed")
        self.assertEqual(record["clears"], ["finding:F1"])
        self.assertEqual(record["evidence_refs"], ["verification:V1"])

    def test_append_event_rejects_unknown_resolution_basis(self) -> None:
        result = self.append_event(
            {
                "type": "consensus",
                "finding": "Unclear resolution.",
                "outcome": "consensus",
                "resolution": "Accepted without basis.",
                "resolution_basis": "unknown",
                "evidence": ["review"],
            },
            check=False,
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("ERROR: consensus resolution_basis must be one of:", result.stderr)

    def test_append_event_accepts_legacy_events_without_new_fields(self) -> None:
        self.append_event(
            {
                "type": "verification",
                "kind": "test",
                "result": "passed",
                "summary": "Legacy verification.",
            }
        )
        self.append_event(
            {
                "type": "consensus",
                "finding": "Legacy finding.",
                "status": "accepted",
                "resolution": "Legacy consensus.",
                "evidence": ["review"],
            }
        )
        self.append_event(
            {
                "type": "review",
                "task_id": "task-a",
                "reviewer": "claude",
                "kind": "diff",
                "result": "passed",
                "findings": [],
            }
        )

        records = self.ledger_records()
        self.assertEqual([record["type"] for record in records], ["verification", "consensus", "review"])
        self.assertEqual(records[1]["outcome"], "consensus")

    def test_blocking_findings_validation(self) -> None:
        base_event: dict[str, object] = {
            "type": "review",
            "task_id": "task-a",
            "reviewer": "claude",
            "kind": "diff",
            "result": "failed",
            "blocking_findings": [
                {
                    "id": "F1",
                    "claim": "The patch skips validation.",
                    "severity": "P1",
                    "file_refs": ["scripts/codex_orchestrator/events.py"],
                    "repro_command": "python3 -m unittest tests.test_evidence_contract -v",
                    "min_repro_attempts": 3,
                }
            ],
        }
        self.append_event(base_event)
        self.assertEqual(self.ledger_records()[-1]["blocking_findings"], base_event["blocking_findings"])

        cases = [
            (
                {
                    "id": "F2",
                    "claim": "Unknown key.",
                    "unknown": "nope",
                },
                "unknown key(s): unknown",
            ),
            (
                {
                    "id": "F3",
                    "claim": "Bad severity.",
                    "severity": "P3",
                },
                "severity must be one of",
            ),
            (
                {
                    "id": "F4",
                },
                "blocking_findings.claim must be a non-empty string",
            ),
            (
                {
                    "id": "F5",
                    "claim": "Bad attempt count.",
                    "min_repro_attempts": 0,
                },
                "min_repro_attempts must be an integer >= 1",
            ),
        ]
        for finding, message in cases:
            event = dict(base_event)
            event["blocking_findings"] = [finding]
            result = self.append_event(event, check=False)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn(message, result.stderr)


if __name__ == "__main__":
    unittest.main()
