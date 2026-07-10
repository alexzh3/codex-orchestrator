from __future__ import annotations

import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from scripts.codex_orchestrator.parse import validate_run

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "codex_orch_parse.py"


def write_ledger(run_dir: Path, records: list[dict[str, object]]) -> None:
    (run_dir / "ledger.jsonl").write_text(
        "".join(json.dumps(record) + "\n" for record in records), encoding="utf-8"
    )


class ValidationTests(unittest.TestCase):
    def make_run(self, root: Path) -> tuple[Path, list[dict[str, object]]]:
        run_dir = root / "run"
        execution_dir = run_dir / "agents" / "codex-impl-01" / "execution-01"
        evidence_dir = run_dir / "evidence"
        execution_dir.mkdir(parents=True)
        evidence_dir.mkdir()
        (execution_dir / "prompt.md").write_text("Implement the task.\n", encoding="utf-8")
        (execution_dir / "events.jsonl").write_text(
            '{"type":"turn.completed"}\n', encoding="utf-8"
        )
        (execution_dir / "handoff.md").write_text("## Status\n\ncomplete\n", encoding="utf-8")
        (evidence_dir / "tests.txt").write_text("1 passed\n", encoding="utf-8")
        records: list[dict[str, object]] = [
            {"type": "run_started"},
            {"type": "task", "id": "task-01", "status": "complete"},
            {
                "type": "execution",
                "task": "task-01",
                "agent": "codex-impl-01",
                "execution": "execution-01",
                "prompt": "agents/codex-impl-01/execution-01/prompt.md",
                "events": "agents/codex-impl-01/execution-01/events.jsonl",
                "handoff": "agents/codex-impl-01/execution-01/handoff.md",
            },
            {
                "type": "execution_result",
                "task": "task-01",
                "agent": "codex-impl-01",
                "execution": "execution-01",
                "status": "complete",
            },
            {
                "type": "verification",
                "id": "check-01",
                "task": "task-01",
                "result": "passed",
                "evidence": ["evidence/tests.txt"],
            },
        ]
        write_ledger(run_dir, records)
        return run_dir, records

    def test_sparse_open_run_is_ready_to_close_and_cli_exits_zero(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_dir, _ = self.make_run(Path(tmp))
            payload = validate_run(run_dir)
            result = subprocess.run(
                [sys.executable, str(SCRIPT), "validate", str(run_dir), "--json"],
                check=False,
                text=True,
                capture_output=True,
                cwd=ROOT,
            )

        self.assertTrue(payload["ok"], payload["issues"])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(json.loads(result.stdout)["ok"])

    def test_unreadable_records_and_unknown_types_are_issues(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "run"
            run_dir.mkdir()
            missing = validate_run(run_dir)
            (run_dir / "ledger.jsonl").write_text(
                '[]\nnot json\n{"type":"mystery"}\n', encoding="utf-8"
            )
            malformed = validate_run(run_dir)

        self.assertFalse(missing["ok"])
        self.assertTrue(any("missing ledger" in issue for issue in missing["issues"]))
        self.assertFalse(malformed["ok"])
        self.assertTrue(any("must be an object" in issue for issue in malformed["issues"]))
        self.assertTrue(any("invalid JSON" in issue for issue in malformed["issues"]))
        self.assertTrue(any("unknown ledger event" in issue for issue in malformed["issues"]))

    def test_start_and_close_markers_have_only_lifecycle_requirements(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_dir, records = self.make_run(Path(tmp))
            close = {"type": "run_closed", "judgment": "passed"}

            write_ledger(run_dir, [*records, close])
            self.assertTrue(validate_run(run_dir)["ok"])

            cases = {
                "missing start": records[1:],
                "start not first": [records[1], records[0], *records[2:]],
                "duplicate start": [records[0], records[0], *records[1:]],
                "duplicate close": [*records, close, close],
                "close not final": [*records, close, {"type": "decision"}],
                "invalid judgment": [*records, {"type": "run_closed", "judgment": "maybe"}],
            }
            for name, case_records in cases.items():
                with self.subTest(name=name):
                    write_ledger(run_dir, case_records)
                    self.assertFalse(validate_run(run_dir)["ok"])

    def test_latest_task_status_must_be_terminal(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_dir, records = self.make_run(Path(tmp))
            earlier_active = {"type": "task", "id": "task-01", "status": "active"}
            write_ledger(run_dir, [records[0], earlier_active, *records[1:]])
            self.assertTrue(validate_run(run_dir)["ok"])

            for status in ("active", "pending", "unknown"):
                with self.subTest(status=status):
                    write_ledger(
                        run_dir,
                        [*records, {"type": "task", "id": "task-01", "status": status}],
                    )
                    payload = validate_run(run_dir)
                    self.assertFalse(payload["ok"])
                    self.assertTrue(any("not terminal" in issue for issue in payload["issues"]))

    def test_execution_and_result_pairing_detects_omissions_and_mismatches(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_dir, records = self.make_run(Path(tmp))
            cases: dict[str, tuple[list[dict[str, object]], str]] = {}

            missing_result = copy.deepcopy(records)
            del missing_result[3]
            cases["missing result"] = missing_result, "no terminal execution_result"

            orphan_result = copy.deepcopy(records)
            del orphan_result[2]
            cases["orphan result"] = orphan_result, "unknown execution"

            duplicate_execution = copy.deepcopy(records)
            duplicate_execution.insert(3, copy.deepcopy(duplicate_execution[2]))
            cases["duplicate execution"] = duplicate_execution, "duplicate execution"

            duplicate_result = copy.deepcopy(records)
            duplicate_result.insert(4, copy.deepcopy(duplicate_result[3]))
            cases["duplicate result"] = duplicate_result, "duplicate execution_result"

            mismatched_task = copy.deepcopy(records)
            mismatched_task[3]["task"] = "task-02"
            cases["task mismatch"] = mismatched_task, "does not match"

            result_first = copy.deepcopy(records)
            result_first[2], result_first[3] = result_first[3], result_first[2]
            cases["result first"] = result_first, "must be recorded before"

            for name, (case_records, expected) in cases.items():
                with self.subTest(name=name):
                    write_ledger(run_dir, case_records)
                    payload = validate_run(run_dir)
                    self.assertFalse(payload["ok"])
                    self.assertTrue(
                        any(expected in issue for issue in payload["issues"]), payload["issues"]
                    )

    def test_declared_files_and_handoff_severity_are_checked(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run_dir, records = self.make_run(root)
            execution_dir = run_dir / "agents" / "codex-impl-01" / "execution-01"

            (execution_dir / "prompt.md").unlink()
            missing_prompt = validate_run(run_dir)
            self.assertFalse(missing_prompt["ok"])
            self.assertTrue(any("prompt file" in issue for issue in missing_prompt["issues"]))
            (execution_dir / "prompt.md").write_text("restored\n", encoding="utf-8")

            (run_dir / "evidence" / "tests.txt").unlink()
            missing_evidence = validate_run(run_dir)
            self.assertFalse(missing_evidence["ok"])
            self.assertTrue(
                any("evidence file" in issue for issue in missing_evidence["issues"])
            )
            (run_dir / "evidence" / "tests.txt").write_text("restored\n", encoding="utf-8")

            external_events = root / "external-rollout.jsonl"
            external_events.write_text('{"type":"turn.completed"}\n', encoding="utf-8")
            records[2]["events"] = str(external_events)
            write_ledger(run_dir, records)
            self.assertTrue(validate_run(run_dir)["ok"])

            (execution_dir / "handoff.md").write_text("", encoding="utf-8")
            complete = validate_run(run_dir)
            self.assertFalse(complete["ok"])
            self.assertTrue(any("handoff is missing or empty" in x for x in complete["issues"]))

            records[3]["status"] = "failed"
            write_ledger(run_dir, records)
            failed = validate_run(run_dir)
            self.assertTrue(failed["ok"], failed["issues"])
            self.assertTrue(any("handoff is missing or empty" in x for x in failed["warnings"]))

    def test_nonpassing_verifications_remain_visible_without_failing_structure(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_dir, records = self.make_run(Path(tmp))
            records[4]["result"] = "failed"
            records.extend(
                [
                    {"type": "verification", "id": "check-02", "result": "inconclusive"},
                    {"type": "verification", "id": "check-03", "result": "skipped"},
                    {"type": "verification", "id": "check-04", "result": "passed"},
                ]
            )
            write_ledger(run_dir, records)
            payload = validate_run(run_dir)

        self.assertTrue(payload["ok"], payload["issues"])
        self.assertEqual(
            [item["id"] for item in payload["non_passing_verifications"]],
            ["check-01", "check-02", "check-03"],
        )

    def test_sparse_decisions_and_optional_metadata_are_not_schema_checked(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_dir, records = self.make_run(Path(tmp))
            records.extend(
                [
                    {
                        "type": "decision",
                        "basis": ["missing-id", "missing-file"],
                        "extra": {"future": True},
                    },
                    {"type": "run_closed", "judgment": "blocked"},
                ]
            )
            write_ledger(run_dir, records)
            payload = validate_run(run_dir)

        self.assertTrue(payload["ok"], payload["issues"])


if __name__ == "__main__":
    unittest.main()
