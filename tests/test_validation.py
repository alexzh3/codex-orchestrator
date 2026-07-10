from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from scripts.codex_orchestrator.parse import validate_run

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "codex_orch_parse.py"


def record(kind: str, **values: object) -> dict[str, object]:
    return {"type": kind, "recorded_at": "2026-07-10T12:00:00Z", **values}


def write_ledger(run_dir: Path, records: list[dict[str, object]]) -> None:
    (run_dir / "ledger.jsonl").write_text(
        "".join(json.dumps(item) + "\n" for item in records), encoding="utf-8"
    )


class ValidationTests(unittest.TestCase):
    def make_run(
        self,
        root: Path,
        *,
        task_status: str = "complete",
        result_status: str = "complete",
        verification_result: str = "passed",
        handoff: bool = True,
    ) -> tuple[Path, list[dict[str, object]]]:
        run_dir = root / "run"
        execution_dir = run_dir / "agents" / "codex-impl-01" / "execution-01"
        evidence_dir = run_dir / "evidence"
        execution_dir.mkdir(parents=True)
        evidence_dir.mkdir()
        (execution_dir / "prompt.md").write_text("Implement the task.\n", encoding="utf-8")
        (execution_dir / "events.jsonl").write_text('{"type":"turn.completed"}\n', encoding="utf-8")
        if handoff:
            (execution_dir / "handoff.md").write_text("## Status\n\ncomplete\n", encoding="utf-8")
        (evidence_dir / "tests.txt").write_text("1 passed\n", encoding="utf-8")
        records = [
            record("run_started", run_id="run", repo=str(root), plugin_ref="test-fixture"),
            record("task", id="task-01", status=task_status),
            record(
                "execution",
                task="task-01",
                agent="codex-impl-01",
                execution="execution-01",
                provider="codex",
                role="implementation",
                mode="headless",
                event_source="exec",
                prompt="agents/codex-impl-01/execution-01/prompt.md",
                events="agents/codex-impl-01/execution-01/events.jsonl",
                handoff="agents/codex-impl-01/execution-01/handoff.md",
            ),
            record(
                "execution_result",
                task="task-01",
                agent="codex-impl-01",
                execution="execution-01",
                status=result_status,
                summary="Agent finished.",
                files_changed=["src/example.py"],
                caveats=[],
            ),
            record(
                "verification",
                id="check-01",
                task="task-01",
                criterion="Focused tests pass",
                method="command",
                result=verification_result,
                check="python -m unittest",
                observation="1 passed",
                evidence=["evidence/tests.txt"],
            ),
            record(
                "decision",
                id="decision-01",
                finding="The checked behavior is correct.",
                outcome="claude_decision",
                resolution="Accept the verified change.",
                basis=["check-01"],
                risk="low",
            ),
        ]
        write_ledger(run_dir, records)
        return run_dir, records

    def test_valid_open_run_is_structurally_ready_to_close(self) -> None:
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
        self.assertEqual(payload["non_passing_verifications"], [])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(json.loads(result.stdout)["ok"])

    def test_nonpassing_verification_is_descriptive_not_a_structural_failure(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_dir, _ = self.make_run(Path(tmp), verification_result="failed")
            payload = validate_run(run_dir)

        self.assertTrue(payload["ok"], payload["issues"])
        self.assertEqual(payload["non_passing_verifications"][0]["id"], "check-01")
        self.assertEqual(payload["non_passing_verifications"][0]["result"], "failed")

    def test_malformed_and_unknown_ledger_records_are_issues(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "run"
            run_dir.mkdir()
            (run_dir / "ledger.jsonl").write_text(
                '{"type":"run_started","run_id":"run","recorded_at":"now"}\n'
                "not json\n"
                '{"type":"mystery","recorded_at":"now"}\n',
                encoding="utf-8",
            )
            payload = validate_run(run_dir)

        self.assertFalse(payload["ok"])
        self.assertTrue(any("invalid JSON" in issue for issue in payload["issues"]))
        self.assertTrue(any("unknown ledger event" in issue for issue in payload["issues"]))

    def test_missing_referenced_paths_and_evidence_are_issues(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_dir, records = self.make_run(Path(tmp))
            (run_dir / "agents" / "codex-impl-01" / "execution-01" / "prompt.md").unlink()
            (run_dir / "evidence" / "tests.txt").unlink()
            payload = validate_run(run_dir)

        self.assertFalse(payload["ok"])
        self.assertTrue(any("prompt path does not exist" in issue for issue in payload["issues"]))
        self.assertTrue(any("evidence path does not exist" in issue for issue in payload["issues"]))

    def test_inflight_execution_and_nonterminal_task_are_issues(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_dir, records = self.make_run(Path(tmp), task_status="active")
            records = [record for record in records if record["type"] != "execution_result"]
            write_ledger(run_dir, records)
            payload = validate_run(run_dir)

        self.assertFalse(payload["ok"])
        self.assertTrue(any("task task-01 is not terminal" in issue for issue in payload["issues"]))
        self.assertTrue(
            any("has no terminal execution_result" in issue for issue in payload["issues"])
        )

    def test_missing_handoff_severity_depends_on_result_status(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            complete_run, _ = self.make_run(Path(tmp) / "complete", handoff=False)
            complete = validate_run(complete_run)
            blocked_run, _ = self.make_run(
                Path(tmp) / "blocked",
                task_status="blocked",
                result_status="blocked",
                handoff=False,
            )
            blocked = validate_run(blocked_run)

        self.assertFalse(complete["ok"])
        self.assertTrue(any("nonempty regular file" in issue for issue in complete["issues"]))
        self.assertTrue(blocked["ok"], blocked["issues"])
        self.assertTrue(any("nonempty regular file" in warning for warning in blocked["warnings"]))

    def test_complete_handoff_rejects_empty_file_and_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            empty_run, _ = self.make_run(Path(tmp) / "empty")
            empty_handoff = empty_run / "agents" / "codex-impl-01" / "execution-01" / "handoff.md"
            empty_handoff.write_text("", encoding="utf-8")
            empty = validate_run(empty_run)

            directory_run, _ = self.make_run(Path(tmp) / "directory")
            directory_handoff = (
                directory_run / "agents" / "codex-impl-01" / "execution-01" / "handoff.md"
            )
            directory_handoff.unlink()
            directory_handoff.mkdir()
            directory = validate_run(directory_run)

            blocked_run, _ = self.make_run(
                Path(tmp) / "blocked-empty",
                task_status="blocked",
                result_status="blocked",
            )
            blocked_handoff = (
                blocked_run / "agents" / "codex-impl-01" / "execution-01" / "handoff.md"
            )
            blocked_handoff.write_text("", encoding="utf-8")
            blocked = validate_run(blocked_run)

        self.assertFalse(empty["ok"])
        self.assertFalse(directory["ok"])
        self.assertTrue(blocked["ok"], blocked["issues"])
        self.assertTrue(any("nonempty regular file" in warning for warning in blocked["warnings"]))

    def test_decision_basis_accepts_prior_ids_and_existing_evidence_handoff_and_repo_paths(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run_dir, records = self.make_run(root)
            repo_file = root / "src" / "example.py"
            repo_file.parent.mkdir()
            repo_file.write_text("VALUE = 1\n", encoding="utf-8")
            decision = next(item for item in records if item["type"] == "decision")
            decision["basis"] = [
                "check-01",
                "agents/codex-impl-01/execution-01/handoff.md",
                "evidence/tests.txt",
                "src/example.py",
            ]
            write_ledger(run_dir, records)
            valid = validate_run(run_dir)

            decision["basis"].append("evidence/missing.txt")
            write_ledger(run_dir, records)
            missing = validate_run(run_dir)

        self.assertTrue(valid["ok"], valid["issues"])
        self.assertFalse(missing["ok"])
        self.assertTrue(any("missing id or path" in issue for issue in missing["issues"]))

    def test_minimal_documented_event_fields_and_enums_are_enforced(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_dir, records = self.make_run(Path(tmp))
            start = next(item for item in records if item["type"] == "run_started")
            for field in ("repo", "plugin_ref"):
                start.pop(field)
            execution = next(item for item in records if item["type"] == "execution")
            for field in ("provider", "role", "mode"):
                execution.pop(field)
            execution["event_source"] = "unknown"
            result = next(item for item in records if item["type"] == "execution_result")
            for field in ("summary", "files_changed", "caveats"):
                result.pop(field)
            verification = next(item for item in records if item["type"] == "verification")
            for field in ("criterion", "method", "check", "observation"):
                verification.pop(field)
            verification["result"] = "maybe"
            decision = next(item for item in records if item["type"] == "decision")
            for field in ("finding", "resolution", "basis", "risk"):
                decision.pop(field)
            decision["outcome"] = "voted"
            records.append(record("run_closed", judgment="passed"))
            write_ledger(run_dir, records)
            payload = validate_run(run_dir)

        self.assertFalse(payload["ok"])
        for field in (
            "repo",
            "plugin_ref",
            "provider",
            "role",
            "mode",
            "summary",
            "files_changed",
            "caveats",
            "criterion",
            "method",
            "check",
            "observation",
            "finding",
            "resolution",
            "basis",
            "risk",
            "validation",
            "risks",
            "follow_ups",
        ):
            self.assertTrue(any(f"field {field}" in issue for issue in payload["issues"]), field)
        self.assertTrue(any("result is not recognized" in issue for issue in payload["issues"]))
        self.assertTrue(any("outcome is not recognized" in issue for issue in payload["issues"]))
        self.assertTrue(
            any("event_source is not recognized" in issue for issue in payload["issues"])
        )

    def test_lifecycle_records_and_decision_references_must_be_ordered(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run_dir, records = self.make_run(root / "task-order")
            start, task, execution, result, verification, decision = records
            write_ledger(run_dir, [start, execution, result, task, verification, decision])
            task_order = validate_run(run_dir)

            run_dir, records = self.make_run(root / "execution-order")
            start, task, execution, result, verification, decision = records
            write_ledger(run_dir, [start, task, result, execution, verification, decision])
            execution_order = validate_run(run_dir)

            run_dir, records = self.make_run(root / "basis-order")
            start, task, execution, result, verification, decision = records
            write_ledger(run_dir, [start, task, execution, result, decision, verification])
            basis_order = validate_run(run_dir)

        self.assertTrue(any("before execution" in issue for issue in task_order["issues"]))
        self.assertTrue(
            any("before execution_result" in issue for issue in execution_order["issues"])
        )
        self.assertTrue(any("appear earlier" in issue for issue in basis_order["issues"]))

    def test_run_paths_are_confined_but_ide_observation_events_may_be_external(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run_dir, records = self.make_run(root / "confined")
            execution = next(item for item in records if item["type"] == "execution")
            original = run_dir / "agents" / "codex-impl-01" / "execution-01"
            external = root / "external"
            external.mkdir()
            external_prompt = external / "prompt.md"
            external_prompt.write_text("outside\n", encoding="utf-8")
            execution["prompt"] = "../outside-prompt.md"
            (run_dir.parent / "outside-prompt.md").write_text("outside\n", encoding="utf-8")
            execution["events"] = str(original / "events.jsonl")
            execution["handoff"] = str(original / "handoff.md")
            verification = next(item for item in records if item["type"] == "verification")
            verification["evidence"] = [str(run_dir / "evidence" / "tests.txt")]
            write_ledger(run_dir, records)
            confined = validate_run(run_dir)

            observe_run, observe_records = self.make_run(root / "observe")
            observe_execution = next(
                item for item in observe_records if item["type"] == "execution"
            )
            rollout = root / "external-rollout.jsonl"
            rollout.write_text('{"payload":{"type":"agent_message"}}\n', encoding="utf-8")
            observe_execution.update(mode="observe", event_source="ide", events=str(rollout))
            observe_execution.pop("prompt")
            write_ledger(observe_run, observe_records)
            observe = validate_run(observe_run)

        self.assertFalse(confined["ok"])
        self.assertTrue(any("prompt path escapes" in issue for issue in confined["issues"]))
        self.assertTrue(
            any("events path must be relative" in issue for issue in confined["issues"])
        )
        self.assertTrue(
            any("handoff path must be relative" in issue for issue in confined["issues"])
        )
        self.assertTrue(
            any("evidence path must be relative" in issue for issue in confined["issues"])
        )
        self.assertTrue(observe["ok"], observe["issues"])

    def test_orphan_result_and_invalid_closure_order_are_issues(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_dir, records = self.make_run(Path(tmp))
            records.extend(
                [
                    record(
                        "run_closed",
                        judgment="passed",
                        summary="Ready.",
                        validation={},
                        risks=[],
                        follow_ups=[],
                    ),
                    record(
                        "execution_result",
                        task="task-01",
                        agent="codex-review-01",
                        execution="execution-99",
                        status="failed",
                        summary="Failed.",
                        files_changed=[],
                        caveats=["No handoff."],
                    ),
                ]
            )
            write_ledger(run_dir, records)
            payload = validate_run(run_dir)

        self.assertFalse(payload["ok"])
        self.assertTrue(any("run_closed must be the final" in issue for issue in payload["issues"]))
        self.assertTrue(any("unknown execution" in issue for issue in payload["issues"]))


if __name__ == "__main__":
    unittest.main()
