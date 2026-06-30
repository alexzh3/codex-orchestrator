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
TEST_COMMAND = "python3 -m unittest discover -s tests -v"


class GateDoctorTests(unittest.TestCase):
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

    def refresh_report_mtime(self) -> None:
        future = time.time() + 60
        os.utime(self.report_path(), (future, future))

    def stale_report_mtime(self) -> None:
        os.utime(self.report_path(), (1, 1))

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
        fresh_report: bool = True,
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
        if fresh_report:
            self.refresh_report_mtime()

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

    def test_gate_ok_appends_gate_result(self) -> None:
        self.make_complete_run(verification_required=[TEST_COMMAND])

        result = self.run_cli("gate", "--repo", str(self.repo), "--run-id", "run")
        payload = json.loads(result.stdout)

        self.assertEqual(result.returncode, 0)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["blocking"], [])
        self.assertEqual(payload["warnings"], [])
        self.assert_gate_result_appended(ok=True)

    def test_gate_second_run_ignores_prior_gate_result_for_report_freshness(self) -> None:
        self.make_complete_run(verification_required=[TEST_COMMAND])
        self.run_cli("gate", "--repo", str(self.repo), "--run-id", "run")

        result = self.run_cli("gate", "--repo", str(self.repo), "--run-id", "run")
        payload = json.loads(result.stdout)

        self.assertEqual(result.returncode, 0)
        self.assertTrue(payload["ok"])
        self.assertFalse(any("stale-report" in item for item in payload["blocking"]))

    def test_gate_blocks_active_task_even_after_run_closed(self) -> None:
        self.init_run()
        self.add_active_task()
        self.add_final_review()
        self.append_event({"type": "run_closed", "status": "complete", "summary": "Closed too early."})
        self.refresh_report_mtime()

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
        self.refresh_report_mtime()

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
        self.refresh_report_mtime()

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
        self.refresh_report_mtime()

        result = self.run_cli("gate", "--repo", str(self.repo), "--run-id", "run", check=False)
        payload = json.loads(result.stdout)

        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(payload["ok"])
        self.assert_blocking_contains(payload, "unresolved-verification")

    def test_gate_allows_failed_verification_with_matching_consensus(self) -> None:
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
        self.refresh_report_mtime()

        result = self.run_cli("gate", "--repo", str(self.repo), "--run-id", "run")
        payload = json.loads(result.stdout)

        self.assertEqual(result.returncode, 0)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["blocking"], [])

    def test_gate_blocks_malformed_ledger_line(self) -> None:
        self.make_complete_run(verification_required=[TEST_COMMAND])
        with self.ledger_path().open("a", encoding="utf-8") as handle:
            handle.write("{not valid json\n")
        self.refresh_report_mtime()

        result = self.run_cli("gate", "--repo", str(self.repo), "--run-id", "run", check=False)
        payload = json.loads(result.stdout)

        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(payload["ok"])
        self.assert_blocking_contains(payload, "malformed-ledger")
        self.assert_gate_result_appended(ok=False)

    def test_gate_blocks_stale_report(self) -> None:
        self.make_complete_run(verification_required=[TEST_COMMAND], fresh_report=False)
        self.stale_report_mtime()

        result = self.run_cli("gate", "--repo", str(self.repo), "--run-id", "run", check=False)
        payload = json.loads(result.stdout)

        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(payload["ok"])
        self.assert_blocking_contains(payload, "stale-report")

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
        self.refresh_report_mtime()

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
        self.refresh_report_mtime()

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
        self.refresh_report_mtime()

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
        self.refresh_report_mtime()

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
        self.refresh_report_mtime()

        result = self.run_cli("gate", "--repo", str(self.repo), "--run-id", "run", check=False)
        payload = json.loads(result.stdout)

        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(payload["ok"])
        self.assert_blocking_contains(payload, "missing-final-review")

        self.add_final_review()
        self.refresh_report_mtime()

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
        self.refresh_report_mtime()

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
        self.refresh_report_mtime()

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
        self.refresh_report_mtime()

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
        self.refresh_report_mtime()

        result = self.run_cli("gate", "--repo", str(self.repo), "--run-id", "run")
        payload = json.loads(result.stdout)

        self.assertEqual(result.returncode, 0)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["blocking"], [])

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
        self.refresh_report_mtime()
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
        self.refresh_report_mtime()

        result = self.run_cli("doctor", "--repo", str(self.repo), "--run-id", "run")
        payload = json.loads(result.stdout)

        self.assertEqual(result.returncode, 0)
        self.assertTrue(payload["ok"])
        self.assertFalse(any("unknown-event" in issue for issue in payload["issues"]))


if __name__ == "__main__":
    unittest.main()
