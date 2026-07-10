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
TEST_COMMAND = "python3 -m unittest discover -s tests -v"


class GateDoctorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self.tmp.name)
        self._verification_event_index = 0

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

    def init_run(self) -> None:
        self.run_cli("init", "--repo", str(self.repo), "--run-id", "run")

    def ledger_dir(self) -> Path:
        return self.repo / ".codex-orchestrator" / "runs" / "run"

    def ledger_path(self) -> Path:
        return self.ledger_dir() / "ledger.jsonl"

    def report_path(self) -> Path:
        return self.ledger_dir() / "report.md"

    def ledger_records(self) -> list[dict[str, object]]:
        records: list[dict[str, object]] = []
        for line in self.ledger_path().read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(record, dict):
                records.append(record)
        return records

    def append_event(self, event: dict[str, object]) -> None:
        self.run_cli("append-event", "--repo", str(self.repo), "--run-id", "run", json.dumps(event))

    def append_raw_event(self, event: dict[str, object]) -> None:
        with self.ledger_path().open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, sort_keys=True) + "\n")

    def add_task(self, *, verification_required: list[str] | None = None) -> None:
        event: dict[str, object] = {
            "type": "task_created",
            "id": "task-a",
            "title": "Implement acceptance gate",
            "status": "complete",
            "files_allowed": ["scripts/codex_orch.py", "tests/test_gate.py"],
            "acceptance": ["gate returns a deterministic result"],
        }
        if verification_required is not None:
            event["verification_required"] = verification_required
        self.append_event(event)

    def add_active_task(self) -> None:
        self.append_event(
            {
                "type": "task_created",
                "id": "task-active",
                "title": "Unfinished task",
                "status": "active",
                "files_allowed": ["scripts/codex_orch.py"],
                "acceptance": ["task is finished"],
            }
        )

    def add_checkpoint(self) -> None:
        self.append_event(
            {
                "type": "task_checkpoint",
                "task_id": "task-a",
                "agent": "codex-a",
                "status": "complete",
                "summary": "Implemented acceptance gate.",
                "files_changed": ["scripts/codex_orch.py", "tests/test_gate.py"],
                "tests_run": [{"command": TEST_COMMAND, "exit_code": 0}],
                "unresolved_blockers": [],
            }
        )

    def add_test_verification(self) -> None:
        self.run_cli(
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
            "Unit tests passed.",
            "--command",
            TEST_COMMAND,
            "--exit-code",
            "0",
        )

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

    def make_complete_run(
        self,
        *,
        checkpoint: bool = True,
        final_review: bool = True,
        test_verification: bool = True,
        verification_required: list[str] | None = None,
    ) -> None:
        self.init_run()
        self.add_task(verification_required=verification_required)
        if checkpoint:
            self.add_checkpoint()
        if test_verification:
            self.add_test_verification()
        if final_review:
            self.add_final_review()
        self.append_event({"type": "run_closed", "status": "complete", "summary": "Run is ready."})

    def assert_blocking_contains(self, payload: dict[str, object], needle: str) -> None:
        blocking = payload.get("blocking")
        self.assertIsInstance(blocking, list)
        self.assertTrue(
            any(isinstance(item, str) and needle in item for item in blocking),
            f"{needle!r} not found in blocking reasons: {blocking}",
        )

    def assert_gate_result_appended(self, *, ok: bool) -> None:
        records = self.ledger_records()
        self.assertEqual(records[-1]["type"], "gate_result")
        self.assertEqual(records[-1]["ok"], ok)

    def add_failed_test_verification(self) -> None:
        self.run_cli(
            "add-verification",
            "--repo",
            str(self.repo),
            "--run-id",
            "run",
            "--kind",
            "test",
            "--result",
            "failed",
            "--summary",
            "Unit tests failed.",
            "--command",
            TEST_COMMAND,
            "--exit-code",
            "1",
        )

    def add_verification_event(self, **fields: object) -> dict[str, object]:
        index = getattr(self, "_verification_event_index", 0) + 1
        self._verification_event_index = index
        record: dict[str, object] = {
            "type": "verification",
            "id": f"V{index}",
            "recorded_at": f"2026-06-29T08:{index:02d}:00Z",
            "kind": "test",
            "result": "failed",
            "summary": f"Verification {index}",
        }
        record.update(fields)
        self.append_event(record)
        return record

    def finish_run(self) -> None:
        self.append_event({"type": "run_closed", "status": "complete", "summary": "Run is ready."})

    def start_gate_ready_run(self) -> None:
        self.init_run()
        self.add_task()
        self.add_checkpoint()
        self.add_final_review()

    def run_doctor_unchanged(self, *, check: bool = False) -> dict[str, object]:
        before = self.ledger_path().read_text(encoding="utf-8")
        result = self.run_cli("doctor", "--repo", str(self.repo), "--run-id", "run", check=check)
        payload = json.loads(result.stdout)
        self.assertEqual(self.ledger_path().read_text(encoding="utf-8"), before)
        return payload

    def test_gate_ok_appends_gate_result(self) -> None:
        self.make_complete_run(verification_required=[TEST_COMMAND])

        result = self.run_cli("gate", "--repo", str(self.repo), "--run-id", "run")
        payload = json.loads(result.stdout)

        self.assertEqual(result.returncode, 0)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["blocking"], [])
        self.assertEqual(payload["warnings"], [])
        self.assert_gate_result_appended(ok=True)

    def test_gate_can_run_repeatedly_before_report_authoring(self) -> None:
        self.make_complete_run(verification_required=[TEST_COMMAND])
        self.run_cli("gate", "--repo", str(self.repo), "--run-id", "run")

        result = self.run_cli("gate", "--repo", str(self.repo), "--run-id", "run")
        payload = json.loads(result.stdout)

        self.assertEqual(result.returncode, 0)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["blocking"], [])

    def test_gate_blocks_active_task_even_after_run_closed(self) -> None:
        self.init_run()
        self.add_active_task()
        self.add_final_review()
        self.append_event({"type": "run_closed", "status": "complete", "summary": "Closed too early."})

        result = self.run_cli("gate", "--repo", str(self.repo), "--run-id", "run", check=False)
        payload = json.loads(result.stdout)

        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(payload["ok"])
        self.assert_blocking_contains(payload, "active-task")

    def test_gate_blocks_completed_task_without_checkpoint(self) -> None:
        self.make_complete_run(checkpoint=False)

        result = self.run_cli("gate", "--repo", str(self.repo), "--run-id", "run", check=False)
        payload = json.loads(result.stdout)

        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(payload["ok"])
        self.assert_blocking_contains(payload, "missing-checkpoint")
        self.assert_gate_result_appended(ok=False)

    def test_gate_blocks_unmet_verification_required(self) -> None:
        self.make_complete_run(test_verification=False, verification_required=[TEST_COMMAND])

        result = self.run_cli("gate", "--repo", str(self.repo), "--run-id", "run", check=False)
        payload = json.loads(result.stdout)

        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(payload["ok"])
        self.assert_blocking_contains(payload, "unmet-verification")

    def test_gate_scopes_verification_requirements_by_task(self) -> None:
        self.init_run()
        self.add_task(verification_required=[TEST_COMMAND])
        self.add_checkpoint()
        self.append_event(
            {
                "type": "task_created",
                "id": "task-b",
                "title": "Update gate tests",
                "status": "complete",
                "files_allowed": ["tests/test_gate.py"],
                "verification_required": [TEST_COMMAND],
            }
        )
        self.append_event(
            {
                "type": "task_checkpoint",
                "task_id": "task-b",
                "agent": "codex-b",
                "status": "complete",
                "summary": "Updated gate tests.",
                "files_changed": ["tests/test_gate.py"],
            }
        )
        self.append_event(
            {
                "type": "verification",
                "kind": "test",
                "result": "passed",
                "summary": "Unit tests passed for task-a.",
                "command": TEST_COMMAND,
                "task_id": "task-a",
            }
        )
        self.add_final_review()
        self.append_event({"type": "run_closed", "status": "complete", "summary": "Run is ready."})

        result = self.run_cli("gate", "--repo", str(self.repo), "--run-id", "run", check=False)
        payload = json.loads(result.stdout)

        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(payload["ok"])
        self.assert_blocking_contains(payload, "unmet-verification: task task-b")

        self.append_event(
            {
                "type": "verification",
                "kind": "test",
                "result": "passed",
                "summary": "Unit tests passed for task-b.",
                "command": TEST_COMMAND,
                "covers_tasks": ["task-b"],
            }
        )

        result = self.run_cli("gate", "--repo", str(self.repo), "--run-id", "run")
        payload = json.loads(result.stdout)

        self.assertEqual(result.returncode, 0)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["blocking"], [])

    def test_gate_blocks_failed_verification_with_unrelated_consensus(self) -> None:
        self.init_run()
        self.add_task()
        self.add_checkpoint()
        self.add_final_review()
        self.add_failed_test_verification()
        self.append_event(
            {
                "type": "consensus",
                "finding": "Documentation wording is acceptable.",
                "outcome": "consensus",
                "resolution": "No action needed for documentation.",
                "risk_level": "none",
                "requires_user": False,
                "evidence": ["Claude and Codex agreed on the docs."],
            }
        )
        self.append_event({"type": "run_closed", "status": "complete", "summary": "Run is ready."})

        result = self.run_cli("gate", "--repo", str(self.repo), "--run-id", "run", check=False)
        payload = json.loads(result.stdout)

        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(payload["ok"])
        self.assert_blocking_contains(payload, "unresolved-verification")

    def test_gate_blocks_failed_executable_verification_with_plain_matching_consensus(self) -> None:
        self.init_run()
        self.add_task()
        self.add_checkpoint()
        self.add_final_review()
        self.add_failed_test_verification()
        self.append_event(
            {
                "type": "consensus",
                "finding": "Unit tests failed.",
                "outcome": "consensus",
                "resolution": f"The failed test check `{TEST_COMMAND}` is accepted for this run.",
                "risk_level": "low",
                "requires_user": False,
                "evidence": ["Claude and Codex agreed this failure is documented."],
            }
        )
        self.append_event({"type": "run_closed", "status": "complete", "summary": "Run is ready."})

        result = self.run_cli("gate", "--repo", str(self.repo), "--run-id", "run", check=False)
        payload = json.loads(result.stdout)

        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(payload["ok"])
        self.assert_blocking_contains(payload, "unresolved-verification")

    def test_gate_allows_command_less_failed_verification_with_matching_consensus(self) -> None:
        self.start_gate_ready_run()
        self.add_verification_event(
            id="V1",
            kind="manual_review",
            result="failed",
            summary="Manual review found a non-executable convention issue.",
        )
        self.append_event(
            {
                "type": "consensus",
                "finding": "Manual review found a non-executable convention issue.",
                "outcome": "consensus",
                "resolution": "Accepted as a documented convention issue.",
                "risk_level": "low",
                "requires_user": False,
                "evidence": ["Claude and Codex agreed this is non-executable."],
            }
        )
        self.finish_run()

        result = self.run_cli("gate", "--repo", str(self.repo), "--run-id", "run")
        payload = json.loads(result.stdout)

        self.assertEqual(result.returncode, 0)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["blocking"], [])

    def test_gate_rerun_passed_clears_failed_executable_verification(self) -> None:
        self.start_gate_ready_run()
        self.add_verification_event(
            id="V1",
            recorded_at="2026-06-29T08:01:00Z",
            kind="test",
            result="failed",
            summary="Unit tests failed.",
            command=TEST_COMMAND,
            task_id="T001",
        )
        self.add_verification_event(
            id="V2",
            recorded_at="2026-06-29T08:02:00Z",
            kind="test",
            result="passed",
            summary="Unit tests passed on rerun.",
            command=TEST_COMMAND,
            task_id="T001",
        )
        self.append_event(
            {
                "type": "consensus",
                "finding": "Unit tests failed.",
                "outcome": "consensus",
                "resolution": "The rerun passed.",
                "resolution_basis": "rerun_passed",
                "requires_user": False,
                "evidence": ["rerun"],
                "clears": ["verification:V1"],
                "evidence_refs": ["verification:V2"],
            }
        )
        self.finish_run()

        result = self.run_cli("gate", "--repo", str(self.repo), "--run-id", "run")
        payload = json.loads(result.stdout)

        self.assertEqual(result.returncode, 0)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["blocking"], [])

    def test_rerun_evidence_after_consensus_does_not_clear(self) -> None:
        self.start_gate_ready_run()
        self.add_verification_event(
            id="V1",
            recorded_at="2026-06-29T08:01:00Z",
            kind="test",
            result="failed",
            summary="Unit tests failed.",
            command=TEST_COMMAND,
            task_id="T001",
        )
        self.append_event(
            {
                "type": "consensus",
                "finding": "Unit tests failed.",
                "outcome": "consensus",
                "resolution": "The rerun will be recorded later.",
                "resolution_basis": "rerun_passed",
                "requires_user": False,
                "evidence": ["rerun"],
                "clears": ["verification:V1"],
                "evidence_refs": ["verification:V2"],
            }
        )
        self.add_verification_event(
            id="V2",
            recorded_at="2026-06-29T08:02:00Z",
            kind="test",
            result="passed",
            summary="Unit tests passed on rerun.",
            command=TEST_COMMAND,
            task_id="T001",
        )
        self.finish_run()

        result = self.run_cli("gate", "--repo", str(self.repo), "--run-id", "run", check=False)
        payload = json.loads(result.stdout)

        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(payload["ok"])
        self.assert_blocking_contains(payload, "unresolved-verification")

        self.append_event(
            {
                "type": "consensus",
                "finding": "Unit tests failed.",
                "outcome": "consensus",
                "resolution": "The rerun has now been recorded.",
                "resolution_basis": "rerun_passed",
                "requires_user": False,
                "evidence": ["rerun"],
                "clears": ["verification:V1"],
                "evidence_refs": ["verification:V2"],
            }
        )

        result = self.run_cli("gate", "--repo", str(self.repo), "--run-id", "run")
        payload = json.loads(result.stdout)

        self.assertEqual(result.returncode, 0)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["blocking"], [])

    def test_gate_rerun_with_different_command_does_not_clear(self) -> None:
        self.start_gate_ready_run()
        self.add_verification_event(id="V1", recorded_at="2026-06-29T08:01:00Z", command=TEST_COMMAND)
        self.add_verification_event(
            id="V2",
            recorded_at="2026-06-29T08:02:00Z",
            result="passed",
            command=f"{TEST_COMMAND} --failfast",
        )
        self.append_event(
            {
                "type": "consensus",
                "finding": "Unit tests failed.",
                "outcome": "consensus",
                "resolution": "A different rerun passed.",
                "resolution_basis": "rerun_passed",
                "requires_user": False,
                "evidence": ["rerun"],
                "clears": ["verification:V1"],
                "evidence_refs": ["verification:V2"],
            }
        )
        self.finish_run()

        result = self.run_cli("gate", "--repo", str(self.repo), "--run-id", "run", check=False)
        payload = json.loads(result.stdout)

        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(payload["ok"])
        self.assert_blocking_contains(payload, "unresolved-verification")

    def test_rerun_link_recomputes_hash_and_rejects_spoofed_command_hash(self) -> None:
        self.start_gate_ready_run()
        stored_hash = "sha256:" + hashlib.sha256(TEST_COMMAND.encode("utf-8")).hexdigest()
        self.add_verification_event(
            id="V1",
            recorded_at="2026-06-29T08:01:00Z",
            command=TEST_COMMAND,
            command_hash=stored_hash,
        )
        self.add_verification_event(
            id="V2",
            recorded_at="2026-06-29T08:02:00Z",
            result="passed",
            command=f"{TEST_COMMAND} --failfast",
            command_hash=stored_hash,
        )
        self.append_event(
            {
                "type": "consensus",
                "finding": "Unit tests failed.",
                "outcome": "consensus",
                "resolution": "A spoofed hash should not clear.",
                "resolution_basis": "rerun_passed",
                "requires_user": False,
                "evidence": ["rerun"],
                "clears": ["verification:V1"],
                "evidence_refs": ["verification:V2"],
            }
        )
        self.finish_run()

        result = self.run_cli("gate", "--repo", str(self.repo), "--run-id", "run", check=False)
        payload = json.loads(result.stdout)

        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(payload["ok"])
        self.assert_blocking_contains(payload, "unresolved-verification")

    def test_same_timestamp_rerun_does_not_clear(self) -> None:
        self.start_gate_ready_run()
        timestamp = "2026-06-29T08:01:00Z"
        self.add_verification_event(id="V1", recorded_at=timestamp, command=TEST_COMMAND)
        self.add_verification_event(id="V2", recorded_at=timestamp, result="passed", command=TEST_COMMAND)
        self.append_event(
            {
                "type": "consensus",
                "finding": "Unit tests failed.",
                "outcome": "consensus",
                "resolution": "Same timestamp rerun.",
                "resolution_basis": "rerun_passed",
                "requires_user": False,
                "evidence": ["rerun"],
                "clears": ["verification:V1"],
                "evidence_refs": ["verification:V2"],
            }
        )
        self.finish_run()

        result = self.run_cli("gate", "--repo", str(self.repo), "--run-id", "run", check=False)
        payload = json.loads(result.stdout)

        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(payload["ok"])
        self.assert_blocking_contains(payload, "unresolved-verification")

    def test_gate_rerun_older_or_task_mismatch_does_not_clear(self) -> None:
        cases = [
            {
                "name": "older",
                "rerun_recorded_at": "2026-06-29T08:00:00Z",
                "rerun_task_id": "T001",
            },
            {
                "name": "task-mismatch",
                "rerun_recorded_at": "2026-06-29T08:02:00Z",
                "rerun_task_id": "T002",
            },
        ]
        for case in cases:
            with self.subTest(case=case["name"]):
                self.tearDown()
                self.setUp()
                self.start_gate_ready_run()
                self.add_verification_event(
                    id="V1",
                    recorded_at="2026-06-29T08:01:00Z",
                    command=TEST_COMMAND,
                    task_id="T001",
                )
                self.add_verification_event(
                    id="V2",
                    recorded_at=case["rerun_recorded_at"],
                    result="passed",
                    command=TEST_COMMAND,
                    task_id=case["rerun_task_id"],
                )
                self.append_event(
                    {
                        "type": "consensus",
                        "finding": "Unit tests failed.",
                        "outcome": "consensus",
                        "resolution": "Rerun did not supersede.",
                        "resolution_basis": "rerun_passed",
                        "requires_user": False,
                        "evidence": ["rerun"],
                        "clears": ["verification:V1"],
                        "evidence_refs": ["verification:V2"],
                    }
                )
                self.finish_run()

                result = self.run_cli("gate", "--repo", str(self.repo), "--run-id", "run", check=False)
                payload = json.loads(result.stdout)

                self.assertNotEqual(result.returncode, 0)
                self.assertFalse(payload["ok"])
                self.assert_blocking_contains(payload, "unresolved-verification")

    def test_rerun_passed_requires_same_verification_kind(self) -> None:
        self.start_gate_ready_run()
        self.add_verification_event(id="V1", recorded_at="2026-06-29T08:01:00Z", kind="test", command=TEST_COMMAND)
        self.add_verification_event(
            id="V2",
            recorded_at="2026-06-29T08:02:00Z",
            kind="manual_review",
            result="passed",
            command=TEST_COMMAND,
        )
        self.append_event(
            {
                "type": "consensus",
                "finding": "Unit tests failed.",
                "outcome": "consensus",
                "resolution": "Different verification kind.",
                "resolution_basis": "rerun_passed",
                "requires_user": False,
                "evidence": ["rerun"],
                "clears": ["verification:V1"],
                "evidence_refs": ["verification:V2"],
            }
        )
        self.finish_run()

        result = self.run_cli("gate", "--repo", str(self.repo), "--run-id", "run", check=False)
        payload = json.loads(result.stdout)

        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(payload["ok"])
        self.assert_blocking_contains(payload, "unresolved-verification")

    def test_acceptance_flag_absent_and_false_match_for_rerun(self) -> None:
        self.start_gate_ready_run()
        self.add_verification_event(
            id="V1",
            recorded_at="2026-06-29T08:01:00Z",
            command=TEST_COMMAND,
            acceptance_test=False,
        )
        self.add_verification_event(
            id="V2",
            recorded_at="2026-06-29T08:02:00Z",
            result="passed",
            command=TEST_COMMAND,
        )
        self.append_event(
            {
                "type": "consensus",
                "finding": "Unit tests failed.",
                "outcome": "consensus",
                "resolution": "The rerun passed.",
                "resolution_basis": "rerun_passed",
                "requires_user": False,
                "evidence": ["rerun"],
                "clears": ["verification:V1"],
                "evidence_refs": ["verification:V2"],
            }
        )
        self.finish_run()

        result = self.run_cli("gate", "--repo", str(self.repo), "--run-id", "run")
        payload = json.loads(result.stdout)

        self.assertEqual(result.returncode, 0)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["blocking"], [])

    def test_duplicate_verification_id_cannot_be_used_as_clear_ref(self) -> None:
        self.start_gate_ready_run()
        self.add_verification_event(id="V1", recorded_at="2026-06-29T08:01:00Z", command=TEST_COMMAND)
        self.add_verification_event(id="V2", recorded_at="2026-06-29T08:02:00Z", result="passed", command=TEST_COMMAND)
        self.add_verification_event(id="V2", recorded_at="2026-06-29T08:03:00Z", result="passed", command=TEST_COMMAND)
        self.append_event(
            {
                "type": "consensus",
                "finding": "Unit tests failed.",
                "outcome": "consensus",
                "resolution": "Duplicate rerun id.",
                "resolution_basis": "rerun_passed",
                "requires_user": False,
                "evidence": ["rerun"],
                "clears": ["verification:V1"],
                "evidence_refs": ["verification:V2"],
            }
        )
        self.finish_run()

        result = self.run_cli("gate", "--repo", str(self.repo), "--run-id", "run", check=False)
        payload = json.loads(result.stdout)

        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(payload["ok"])
        self.assert_blocking_contains(payload, "unresolved-verification")

    def test_evidence_refs_do_not_address_verification(self) -> None:
        self.start_gate_ready_run()
        self.add_verification_event(id="V1", command=TEST_COMMAND, summary="Unit tests failed.")
        self.append_event(
            {
                "type": "consensus",
                "finding": "Documentation wording is acceptable.",
                "outcome": "consensus",
                "resolution": "No action needed for documentation.",
                "resolution_basis": "accepted_risk",
                "requires_user": False,
                "evidence": ["review"],
                "evidence_refs": ["verification:V1"],
            }
        )
        self.finish_run()

        result = self.run_cli("gate", "--repo", str(self.repo), "--run-id", "run", check=False)
        payload = json.loads(result.stdout)

        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(payload["ok"])
        self.assert_blocking_contains(payload, "unresolved-verification")

    def test_gate_consensus_with_clears_refs_disables_text_matching(self) -> None:
        self.start_gate_ready_run()
        self.add_verification_event(id="V1", command=TEST_COMMAND, summary="Unit tests failed.")
        self.append_event(
            {
                "type": "consensus",
                "finding": "Unit tests failed.",
                "outcome": "consensus",
                "resolution": f"The failed check `{TEST_COMMAND}` is accepted.",
                "resolution_basis": "accepted_risk",
                "requires_user": False,
                "evidence": ["review"],
                "clears": ["verification:V9"],
            }
        )
        self.finish_run()

        result = self.run_cli("gate", "--repo", str(self.repo), "--run-id", "run", check=False)
        payload = json.loads(result.stdout)

        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(payload["ok"])
        self.assert_blocking_contains(payload, "unresolved-verification")

    def test_repro_not_reproduced_requires_two_attempts_for_stochastic(self) -> None:
        for attempts, should_pass in ((1, False), (2, True)):
            with self.subTest(attempts=attempts):
                self.tearDown()
                self.setUp()
                self.start_gate_ready_run()
                self.add_verification_event(
                    id="V1",
                    recorded_at="2026-06-29T08:01:00Z",
                    command=TEST_COMMAND,
                    stochastic=True,
                )
                self.add_verification_event(
                    id="V2",
                    recorded_at="2026-06-29T08:02:00Z",
                    result="passed",
                    command=TEST_COMMAND,
                    attempt_count=attempts,
                )
                self.append_event(
                    {
                        "type": "consensus",
                        "finding": "Stochastic test failed.",
                        "outcome": "consensus",
                        "resolution": "The issue was not reproduced.",
                        "resolution_basis": "repro_not_reproduced",
                        "requires_user": False,
                        "evidence": ["rerun"],
                        "clears": ["verification:V1"],
                        "evidence_refs": ["verification:V2"],
                    }
                )
                self.finish_run()

                result = self.run_cli("gate", "--repo", str(self.repo), "--run-id", "run", check=should_pass)
                payload = json.loads(result.stdout)

                self.assertEqual(payload["ok"], should_pass)
                if should_pass:
                    self.assertEqual(result.returncode, 0)
                    self.assertEqual(payload["blocking"], [])
                else:
                    self.assertNotEqual(result.returncode, 0)
                    self.assert_blocking_contains(payload, "unresolved-verification")

    def test_accepted_risk_cannot_clear_executable_or_acceptance(self) -> None:
        cases = [
            {"name": "executable", "fields": {"command": TEST_COMMAND}, "should_pass": False},
            {"name": "acceptance", "fields": {"kind": "manual_review", "acceptance_test": True}, "should_pass": False},
            {"name": "plain", "fields": {"kind": "manual_review"}, "should_pass": True},
        ]
        for case in cases:
            with self.subTest(case=case["name"]):
                self.tearDown()
                self.setUp()
                self.start_gate_ready_run()
                self.add_verification_event(id="V1", summary="Risk accepted.", **case["fields"])
                self.append_event(
                    {
                        "type": "consensus",
                        "finding": "Risk accepted.",
                        "outcome": "consensus",
                        "resolution": "Accepted risk.",
                        "resolution_basis": "accepted_risk",
                        "requires_user": False,
                        "evidence": ["risk reviewed"],
                        "clears": ["verification:V1"],
                    }
                )
                self.finish_run()

                result = self.run_cli("gate", "--repo", str(self.repo), "--run-id", "run", check=case["should_pass"])
                payload = json.loads(result.stdout)

                self.assertEqual(payload["ok"], case["should_pass"])
                if case["should_pass"]:
                    self.assertEqual(payload["blocking"], [])
                else:
                    self.assert_blocking_contains(payload, "unresolved-verification")

    def test_user_override_clears_executable_but_not_acceptance(self) -> None:
        cases = [
            {"name": "executable", "fields": {"command": TEST_COMMAND}, "should_pass": True},
            {"name": "acceptance", "fields": {"kind": "manual_review", "acceptance_test": True}, "should_pass": False},
        ]
        for case in cases:
            with self.subTest(case=case["name"]):
                self.tearDown()
                self.setUp()
                self.start_gate_ready_run()
                self.add_verification_event(id="V1", summary="User override.", **case["fields"])
                self.append_event(
                    {
                        "type": "consensus",
                        "finding": "User override.",
                        "outcome": "consensus",
                        "resolution": "User override recorded.",
                        "resolution_basis": "user_override",
                        "requires_user": False,
                        "evidence": ["user approved"],
                        "clears": ["verification:V1"],
                    }
                )
                self.finish_run()

                result = self.run_cli("gate", "--repo", str(self.repo), "--run-id", "run", check=case["should_pass"])
                payload = json.loads(result.stdout)

                self.assertEqual(payload["ok"], case["should_pass"])
                if case["should_pass"]:
                    self.assertEqual(payload["blocking"], [])
                else:
                    self.assert_blocking_contains(payload, "unresolved-verification")

    def test_gate_blocks_malformed_ledger_line(self) -> None:
        self.make_complete_run(verification_required=[TEST_COMMAND])
        with self.ledger_path().open("a", encoding="utf-8") as handle:
            handle.write("{not valid json\n")

        result = self.run_cli("gate", "--repo", str(self.repo), "--run-id", "run", check=False)
        payload = json.loads(result.stdout)

        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(payload["ok"])
        self.assert_blocking_contains(payload, "malformed-ledger")
        self.assert_gate_result_appended(ok=False)

    def test_gate_does_not_require_report_before_final_authoring(self) -> None:
        self.make_complete_run(verification_required=[TEST_COMMAND])
        self.report_path().unlink()

        result = self.run_cli("gate", "--repo", str(self.repo), "--run-id", "run")
        payload = json.loads(result.stdout)

        self.assertEqual(result.returncode, 0)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["blocking"], [])

    def test_gate_blocks_unresolved_user_action_consensus(self) -> None:
        self.make_complete_run(verification_required=[TEST_COMMAND])
        self.append_event(
            {
                "type": "consensus",
                "finding": "Release owner needs to choose a path.",
                "outcome": "user_action_required",
                "resolution": "Wait for a human decision.",
                "risk_level": "high",
                "requires_user": True,
                "evidence": ["Claude requested a decision."],
            }
        )

        result = self.run_cli("gate", "--repo", str(self.repo), "--run-id", "run", check=False)
        payload = json.loads(result.stdout)

        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(payload["ok"])
        self.assert_blocking_contains(payload, "unresolved-consensus")

    def test_gate_blocks_missing_final_review(self) -> None:
        self.make_complete_run(final_review=False, verification_required=[TEST_COMMAND])

        result = self.run_cli("gate", "--repo", str(self.repo), "--run-id", "run", check=False)
        payload = json.loads(result.stdout)

        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(payload["ok"])
        self.assert_blocking_contains(payload, "missing-final-review")

    def test_gate_requires_run_wide_final_review_verification(self) -> None:
        self.make_complete_run(final_review=False, verification_required=[TEST_COMMAND])
        self.append_event(
            {
                "type": "verification",
                "kind": "manual_review",
                "result": "passed",
                "task_id": "task-a",
                "scope": "task",
                "summary": "Task-scoped review passed.",
            }
        )

        result = self.run_cli("gate", "--repo", str(self.repo), "--run-id", "run", check=False)
        payload = json.loads(result.stdout)

        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(payload["ok"])
        self.assert_blocking_contains(payload, "missing-final-review")

        self.append_event(
            {
                "type": "verification",
                "kind": "manual_review",
                "result": "passed",
                "scope": "global",
                "summary": "Run-wide final review passed.",
            }
        )

        result = self.run_cli("gate", "--repo", str(self.repo), "--run-id", "run")
        payload = json.loads(result.stdout)

        self.assertEqual(result.returncode, 0)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["blocking"], [])

    def test_gate_does_not_treat_task_scoped_typed_review_as_run_wide_final_review(self) -> None:
        self.make_complete_run(final_review=False, verification_required=[TEST_COMMAND])
        self.append_event(
            {
                "type": "review",
                "task_id": "task-a",
                "reviewer": "claude",
                "kind": "test",
                "result": "passed",
                "summary": "Test-focused review passed.",
                "findings": [],
            }
        )

        result = self.run_cli("gate", "--repo", str(self.repo), "--run-id", "run", check=False)
        payload = json.loads(result.stdout)

        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(payload["ok"])
        self.assert_blocking_contains(payload, "missing-final-review")

        self.append_event(
            {
                "type": "review",
                "task_id": "task-a",
                "reviewer": "claude",
                "kind": "test",
                "result": "passed",
                "final": True,
                "summary": "Explicit final review passed.",
                "findings": [],
            }
        )

        result = self.run_cli("gate", "--repo", str(self.repo), "--run-id", "run", check=False)
        payload = json.loads(result.stdout)

        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(payload["ok"])
        self.assert_blocking_contains(payload, "missing-final-review")

        self.add_final_review()

        result = self.run_cli("gate", "--repo", str(self.repo), "--run-id", "run")
        payload = json.loads(result.stdout)

        self.assertEqual(result.returncode, 0)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["blocking"], [])

    def test_gate_blocks_file_claim_conflicts(self) -> None:
        self.make_complete_run(verification_required=[TEST_COMMAND])
        self.append_event(
            {
                "type": "file_claimed",
                "task_id": "claim-a",
                "agent": "codex-a",
                "allow": ["scripts/*"],
            }
        )
        self.append_event(
            {
                "type": "file_claimed",
                "task_id": "claim-b",
                "agent": "codex-b",
                "allow": ["scripts/codex_orch.py"],
            }
        )

        result = self.run_cli("gate", "--repo", str(self.repo), "--run-id", "run", check=False)
        payload = json.loads(result.stdout)

        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(payload["ok"])
        self.assert_blocking_contains(payload, "file-claim-conflict: claim-a and claim-b")

    def test_gate_blocks_unclaimed_changes_outside_allowlist(self) -> None:
        self.make_complete_run(verification_required=[TEST_COMMAND])
        self.append_event(
            {
                "type": "task_checkpoint",
                "task_id": "task-a",
                "agent": "codex-a",
                "status": "complete",
                "summary": "Changed an unclaimed file.",
                "files_changed": ["docs/outside.md"],
            }
        )

        result = self.run_cli("gate", "--repo", str(self.repo), "--run-id", "run", check=False)
        payload = json.loads(result.stdout)

        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(payload["ok"])
        self.assert_blocking_contains(payload, "unclaimed-change: task task-a changed docs/outside.md")

    def test_gate_blocks_changes_for_explicit_empty_file_allowlist(self) -> None:
        self.make_complete_run(verification_required=[TEST_COMMAND])
        self.append_event(
            {
                "type": "task_created",
                "id": "task-no-edits",
                "title": "Inspect without editing",
                "status": "complete",
                "files_allowed": [],
            }
        )
        self.append_event(
            {
                "type": "task_checkpoint",
                "task_id": "task-no-edits",
                "agent": "codex-b",
                "status": "complete",
                "summary": "Changed files despite no-edit scope.",
                "files_changed": ["README.md"],
            }
        )

        result = self.run_cli("gate", "--repo", str(self.repo), "--run-id", "run", check=False)
        payload = json.loads(result.stdout)

        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(payload["ok"])
        self.assert_blocking_contains(payload, "unclaimed-change: task task-no-edits changed README.md")

    def test_gate_allows_claimed_changes_and_legacy_unscoped_task_changes(self) -> None:
        self.make_complete_run(verification_required=[TEST_COMMAND])
        self.append_event(
            {
                "type": "task_created",
                "id": "task-unscoped",
                "title": "Legacy task without file scope",
                "status": "complete",
            }
        )
        self.append_event(
            {
                "type": "task_checkpoint",
                "task_id": "task-unscoped",
                "agent": "codex-b",
                "status": "complete",
                "summary": "Changed files without a declared allowlist.",
                "files_changed": ["README.md"],
            }
        )

        result = self.run_cli("gate", "--repo", str(self.repo), "--run-id", "run")
        payload = json.loads(result.stdout)

        self.assertEqual(result.returncode, 0)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["blocking"], [])

    def test_doctor_flags_dangling_and_malformed_refs(self) -> None:
        self.start_gate_ready_run()
        self.append_event(
            {
                "type": "consensus",
                "finding": "Reference hygiene.",
                "outcome": "consensus",
                "resolution": "References are intentionally bad.",
                "requires_user": False,
                "evidence": ["review"],
                "clears": ["verification:V404", "not-a-ref"],
                "evidence_refs": ["finding:F404", "also-bad"],
            }
        )

        payload = self.run_doctor_unchanged()
        issues = payload["issues"]

        self.assertFalse(payload["ok"])
        self.assertTrue(
            any(
                "malformed-ref: consensus 'Reference hygiene.' clears entry 'not-a-ref'" in issue
                for issue in issues
            )
        )
        self.assertTrue(
            any(
                "malformed-ref: consensus 'Reference hygiene.' evidence_refs entry 'also-bad'" in issue
                for issue in issues
            )
        )
        self.assertTrue(
            any(
                "dangling-ref: consensus 'Reference hygiene.' references unknown verification id 'V404'" in issue
                for issue in issues
            )
        )
        self.assertTrue(
            any(
                "dangling-ref: consensus 'Reference hygiene.' references unknown finding id 'F404'" in issue
                for issue in issues
            )
        )

    def test_doctor_flags_invalid_rerun_link_and_duplicate_ids(self) -> None:
        self.start_gate_ready_run()
        self.add_verification_event(id="V1", recorded_at="2026-06-29T08:01:00Z", command=TEST_COMMAND)
        self.add_verification_event(id="V2", recorded_at="2026-06-29T08:02:00Z", result="passed", command=TEST_COMMAND)
        self.add_verification_event(id="V2", recorded_at="2026-06-29T08:03:00Z", result="passed", command=TEST_COMMAND)
        self.add_verification_event(
            id="V3",
            recorded_at="2026-06-29T08:04:00Z",
            result="passed",
            command=f"{TEST_COMMAND} --failfast",
        )
        self.append_event(
            {
                "type": "consensus",
                "finding": "Backfilled rerun.",
                "outcome": "consensus",
                "resolution": "This cites a rerun that appears later in the ledger.",
                "resolution_basis": "rerun_passed",
                "requires_user": False,
                "evidence": ["rerun"],
                "clears": ["verification:V1"],
                "evidence_refs": ["verification:V4"],
            }
        )
        self.add_verification_event(
            id="V4",
            recorded_at="2026-06-29T08:05:00Z",
            result="passed",
            command=TEST_COMMAND,
        )
        self.append_event(
            {
                "type": "consensus",
                "finding": "Unit tests failed.",
                "outcome": "consensus",
                "resolution": "Invalid rerun link.",
                "resolution_basis": "rerun_passed",
                "requires_user": False,
                "evidence": ["rerun"],
                "clears": ["verification:V1"],
                "evidence_refs": ["verification:V3"],
            }
        )

        payload = self.run_doctor_unchanged()
        issues = payload["issues"]

        self.assertFalse(payload["ok"])
        self.assertTrue(
            any(
                "invalid-rerun-link: consensus 'Unit tests failed.' link 'V3' "
                "does not supersede verification 'V1' (command hash mismatch)" in issue
                for issue in issues
            )
        )
        self.assertTrue(
            any(
                "invalid-rerun-link: consensus 'Backfilled rerun.' link 'V4' "
                "does not supersede verification 'V1' (recorded after consensus)" in issue
                for issue in issues
            )
        )
        self.assertTrue(any("duplicate-verification-id: verification id 'V2' recorded 2 times" in issue for issue in issues))

    def test_doctor_flags_ineffective_clear_on_executable_target(self) -> None:
        self.start_gate_ready_run()
        self.add_verification_event(id="V1", command=TEST_COMMAND, summary="Executable failure.")
        self.append_event(
            {
                "type": "consensus",
                "finding": "Executable failure.",
                "outcome": "consensus",
                "resolution": "Accepted risk cannot clear this executable check.",
                "resolution_basis": "accepted_risk",
                "requires_user": False,
                "evidence": ["risk reviewed"],
                "clears": ["verification:V1"],
            }
        )

        payload = self.run_doctor_unchanged()

        self.assertFalse(payload["ok"])
        self.assertTrue(
            any(
                "ineffective-clear: consensus 'Executable failure.' (basis accepted_risk) "
                "cannot clear verification 'V1' (executable command)" in issue
                for issue in payload["issues"]
            )
        )

    def test_doctor_flags_spoofed_stored_command_hash(self) -> None:
        self.start_gate_ready_run()
        spoofed_hash = "sha256:" + hashlib.sha256(TEST_COMMAND.encode("utf-8")).hexdigest()
        self.add_verification_event(
            id="V1",
            result="passed",
            command=f"{TEST_COMMAND} --failfast",
            command_hash=spoofed_hash,
        )

        payload = self.run_doctor_unchanged()

        self.assertFalse(payload["ok"])
        self.assertTrue(
            any(
                "command-hash-mismatch: verification 'V1' stored command_hash does not match its command" in issue
                for issue in payload["issues"]
            )
        )

    def test_doctor_flags_missing_checkpoint_and_dispatch_paths_without_mutating_ledger(self) -> None:
        self.init_run()
        self.append_raw_event(
            {
                "type": "task_created",
                "recorded_at": "2026-06-29T08:00:00Z",
                "id": "task-a",
                "title": "Incomplete task",
                "status": "complete",
            }
        )
        self.append_raw_event(
            {
                "type": "dispatch_started",
                "recorded_at": "2026-06-29T08:01:00Z",
                "task_id": "task-a",
                "agent": "codex-a",
                "mode": "exec",
                "prompt_path": "prompts/task-a.md",
            }
        )
        before = self.ledger_path().read_text(encoding="utf-8")

        result = self.run_cli("doctor", "--repo", str(self.repo), "--run-id", "run", check=False)
        payload = json.loads(result.stdout)

        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(payload["ok"])
        issues = payload["issues"]
        self.assertTrue(any("missing-checkpoint" in issue for issue in issues))
        self.assertTrue(any("dispatch-missing-paths" in issue and "log_path" in issue for issue in issues))
        self.assertEqual(self.ledger_path().read_text(encoding="utf-8"), before)

    def test_doctor_allows_legacy_change_events(self) -> None:
        self.init_run()
        self.append_event({"type": "change", "summary": "Legacy change evidence."})

        result = self.run_cli("doctor", "--repo", str(self.repo), "--run-id", "run")
        payload = json.loads(result.stdout)

        self.assertEqual(result.returncode, 0)
        self.assertTrue(payload["ok"])
        self.assertFalse(any("unknown-event" in issue for issue in payload["issues"]))


if __name__ == "__main__":
    unittest.main()
