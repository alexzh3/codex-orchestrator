from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "codex_orch.py"


class TaskProtocolTests(unittest.TestCase):
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

    def ledger_records(self) -> list[dict[str, object]]:
        return [
            json.loads(line)
            for line in (self.ledger_dir() / "ledger.jsonl").read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]

    def append_event(self, event: dict[str, object], *, check: bool = True) -> subprocess.CompletedProcess[str]:
        return self.run_cli("append-event", "--repo", str(self.repo), "--run-id", "run", json.dumps(event), check=check)

    def test_append_event_accepts_and_rejects_new_typed_events(self) -> None:
        self.init_run()
        valid_events = [
            {
                "type": "task_created",
                "id": "task-a",
                "title": "Build task protocol data layer",
                "status": "active",
                "owner": "codex-a",
                "goal": "Implement durable task protocol records.",
                "depends_on": [],
                "context": ["The orchestrator stores task state in ledger.jsonl."],
                "constraints": ["Keep typed event changes backward-compatible."],
                "files_allowed": ["scripts/codex_orch.py"],
                "files_forbidden": ["scripts/codex_orch_parse.py"],
                "acceptance": ["unit tests pass"],
                "verification_required": ["python3 -m unittest discover -s tests -v"],
            },
            {"type": "task_updated", "id": "task-a", "status": "blocked", "notes": "Waiting on review."},
            {
                "type": "file_claimed",
                "task_id": "task-a",
                "agent": "codex-a",
                "allow": ["scripts/codex_orch.py"],
                "forbid": ["scripts/codex_orch_parse.py"],
            },
            {
                "type": "dispatch_started",
                "task_id": "task-a",
                "agent": "codex-a",
                "mode": "exec",
                "prompt_path": "prompts/task-a.md",
                "log_path": "logs/task-a.jsonl",
                "fresh_session": True,
                "reuse_reason": "same task follow-up",
                "worktree": "/tmp/task-a",
            },
            {"type": "dispatch_completed", "task_id": "task-a", "agent": "codex-a", "status": "complete"},
            {
                "type": "task_checkpoint",
                "task_id": "task-a",
                "agent": "codex-a",
                "status": "complete",
                "summary": "Implemented task protocol data layer.",
                "files_changed": ["scripts/codex_orch.py"],
                "tests_run": [{"command": "python3 -m unittest discover -s tests -v", "exit_code": 0}],
                "unresolved_blockers": [],
            },
            {
                "type": "verification",
                "kind": "test",
                "result": "passed",
                "summary": "Unit tests passed.",
                "command": "python3 -m unittest discover -s tests -v",
                "task_id": "task-a",
                "covers_tasks": ["task-b"],
                "scope": "global",
            },
            {
                "type": "review",
                "task_id": "task-a",
                "reviewer": "claude",
                "kind": "diff",
                "result": "passed",
                "command": "codex exec review --base main",
                "prompt_path": "prompts/review.md",
                "log_path": "logs/review.jsonl",
                "summary": "No blocking findings.",
                "findings": [],
            },
            {"type": "gate_result", "ok": True, "blocking": [], "warnings": []},
            {"type": "run_closed", "status": "complete", "summary": "Run accepted."},
        ]
        invalid_events = [
            (
                {"type": "task_created", "id": "task-a", "title": "Bad status", "status": "done"},
                "task_created status must be one of",
            ),
            ({"type": "task_updated", "id": "task-a"}, "task_updated event missing required"),
            (
                {"type": "file_claimed", "task_id": "task-a", "agent": "codex-a", "allow": []},
                "file_claimed field allow must be a non-empty string array",
            ),
            (
                {
                    "type": "dispatch_started",
                    "task_id": "task-a",
                    "agent": "codex-a",
                    "mode": "batch",
                    "prompt_path": "prompts/task-a.md",
                    "log_path": "logs/task-a.jsonl",
                },
                "dispatch_started mode must be one of",
            ),
            (
                {"type": "dispatch_completed", "task_id": "task-a", "agent": "codex-a", "status": "done"},
                "dispatch_completed status must be one of",
            ),
            (
                {
                    "type": "task_checkpoint",
                    "task_id": "task-a",
                    "agent": "codex-a",
                    "status": "complete",
                    "summary": "Missing files_changed.",
                },
                "task_checkpoint event missing required",
            ),
            (
                {"type": "review", "task_id": "task-a", "reviewer": "claude", "kind": "security", "result": "passed"},
                "review kind must be one of",
            ),
            ({"type": "gate_result", "blocking": []}, "gate_result event missing required"),
            ({"type": "run_closed", "status": "done"}, "run_closed status must be one of"),
        ]

        for event in valid_events:
            with self.subTest(valid=event["type"]):
                result = self.append_event(event)
                payload = json.loads(result.stdout)
                self.assertTrue(payload["ok"])
                self.assertEqual(payload["event"]["type"], event["type"])
                self.assertIn("recorded_at", payload["event"])

        for event, message in invalid_events:
            with self.subTest(invalid=event["type"]):
                result = self.append_event(event, check=False)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(message, result.stderr)

    def test_claim_files_writes_file_claimed_event(self) -> None:
        self.init_run()
        result = self.run_cli(
            "claim-files",
            "--repo",
            str(self.repo),
            "--run-id",
            "run",
            "--task-id",
            "task-a",
            "--agent",
            "codex-a",
            "--allow",
            "scripts/*.py",
            "--allow",
            "tests/*.py",
            "--forbid",
            "scripts/codex_orch_parse.py",
        )

        payload = json.loads(result.stdout)
        self.assertTrue(payload["ok"])
        records = self.ledger_records()
        self.assertEqual(records[-1]["type"], "file_claimed")
        self.assertEqual(records[-1]["task_id"], "task-a")
        self.assertEqual(records[-1]["agent"], "codex-a")
        self.assertEqual(records[-1]["allow"], ["scripts/*.py", "tests/*.py"])
        self.assertEqual(records[-1]["forbid"], ["scripts/codex_orch_parse.py"])
        self.assertIn("recorded_at", records[-1])

    def test_add_verification_task_scope_only_satisfies_matching_task(self) -> None:
        self.init_run()
        for task_id in ("task-a", "task-b"):
            self.append_event(
                {
                    "type": "task_created",
                    "id": task_id,
                    "title": f"Task {task_id}",
                    "status": "complete",
                    "verification_required": ["test"],
                }
            )
            self.append_event(
                {
                    "type": "task_checkpoint",
                    "task_id": task_id,
                    "agent": "codex",
                    "status": "complete",
                    "summary": f"Completed {task_id}.",
                    "files_changed": [],
                }
            )
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
            "Scoped unit tests passed",
            "--task-id",
            "task-a",
            "--scope",
            "task",
        )
        self.run_cli(
            "add-verification",
            "--repo",
            str(self.repo),
            "--run-id",
            "run",
            "--kind",
            "manual_review",
            "--result",
            "passed",
            "--summary",
            "Final review passed",
        )

        verification = [record for record in self.ledger_records() if record.get("summary") == "Scoped unit tests passed"]
        self.assertEqual(len(verification), 1)
        self.assertEqual(verification[0]["task_id"], "task-a")
        self.assertEqual(verification[0]["scope"], "task")

        self.run_cli("report", "--repo", str(self.repo), "--run-id", "run")
        result = self.run_cli("gate", "--repo", str(self.repo), "--run-id", "run", check=False)
        payload = json.loads(result.stdout)
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(payload["ok"])
        self.assertIn("unmet-verification: task task-b requires test", payload["blocking"])
        self.assertNotIn("unmet-verification: task task-a requires test", payload["blocking"])

    def test_check_conflicts_reports_ok_for_disjoint_active_claims(self) -> None:
        self.init_run()
        self.run_cli(
            "claim-files",
            "--repo",
            str(self.repo),
            "--run-id",
            "run",
            "--task-id",
            "task-a",
            "--agent",
            "codex-a",
            "--allow",
            "scripts/*.py",
        )
        self.run_cli(
            "claim-files",
            "--repo",
            str(self.repo),
            "--run-id",
            "run",
            "--task-id",
            "task-b",
            "--agent",
            "codex-b",
            "--allow",
            "docs/*.md",
        )

        result = self.run_cli("check-conflicts", "--repo", str(self.repo), "--run-id", "run")
        payload = json.loads(result.stdout)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["conflicts"], [])

    def test_check_conflicts_exits_nonzero_for_overlapping_active_claims(self) -> None:
        self.init_run()
        self.run_cli(
            "claim-files",
            "--repo",
            str(self.repo),
            "--run-id",
            "run",
            "--task-id",
            "task-a",
            "--agent",
            "codex-a",
            "--allow",
            "scripts/*",
        )
        self.run_cli(
            "claim-files",
            "--repo",
            str(self.repo),
            "--run-id",
            "run",
            "--task-id",
            "task-b",
            "--agent",
            "codex-b",
            "--allow",
            "scripts/codex_orch.py",
        )

        result = self.run_cli("check-conflicts", "--repo", str(self.repo), "--run-id", "run", check=False)
        payload = json.loads(result.stdout)
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["conflicts"][0]["task_a"], "task-a")
        self.assertEqual(payload["conflicts"][0]["task_b"], "task-b")
        self.assertEqual(
            payload["conflicts"][0]["overlap"],
            [{"allow_a": "scripts/*", "allow_b": "scripts/codex_orch.py"}],
        )

    def test_check_conflicts_overapproximates_same_directory_wildcards(self) -> None:
        self.init_run()
        self.run_cli(
            "claim-files",
            "--repo",
            str(self.repo),
            "--run-id",
            "run",
            "--task-id",
            "task-a",
            "--agent",
            "codex-a",
            "--allow",
            "src/*_service.py",
        )
        self.run_cli(
            "claim-files",
            "--repo",
            str(self.repo),
            "--run-id",
            "run",
            "--task-id",
            "task-b",
            "--agent",
            "codex-b",
            "--allow",
            "src/user_*.py",
        )

        result = self.run_cli("check-conflicts", "--repo", str(self.repo), "--run-id", "run", check=False)
        payload = json.loads(result.stdout)
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["conflicts"][0]["task_a"], "task-a")
        self.assertEqual(payload["conflicts"][0]["task_b"], "task-b")
        self.assertEqual(
            payload["conflicts"][0]["overlap"],
            [{"allow_a": "src/*_service.py", "allow_b": "src/user_*.py"}],
        )

    def test_check_conflicts_allows_wildcards_in_disjoint_directories(self) -> None:
        self.init_run()
        self.run_cli(
            "claim-files",
            "--repo",
            str(self.repo),
            "--run-id",
            "run",
            "--task-id",
            "task-a",
            "--agent",
            "codex-a",
            "--allow",
            "src/a/**",
        )
        self.run_cli(
            "claim-files",
            "--repo",
            str(self.repo),
            "--run-id",
            "run",
            "--task-id",
            "task-b",
            "--agent",
            "codex-b",
            "--allow",
            "src/b/**",
        )

        result = self.run_cli("check-conflicts", "--repo", str(self.repo), "--run-id", "run")
        payload = json.loads(result.stdout)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["conflicts"], [])

    def test_failed_dispatch_does_not_release_file_claims(self) -> None:
        self.init_run()
        self.run_cli(
            "claim-files",
            "--repo",
            str(self.repo),
            "--run-id",
            "run",
            "--task-id",
            "task-a",
            "--agent",
            "codex-a",
            "--allow",
            "scripts/*",
        )
        self.append_event({"type": "dispatch_completed", "task_id": "task-a", "agent": "codex-a", "status": "failed"})
        self.run_cli(
            "claim-files",
            "--repo",
            str(self.repo),
            "--run-id",
            "run",
            "--task-id",
            "task-b",
            "--agent",
            "codex-b",
            "--allow",
            "scripts/codex_orch.py",
        )

        result = self.run_cli("check-conflicts", "--repo", str(self.repo), "--run-id", "run", check=False)
        payload = json.loads(result.stdout)
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["conflicts"][0]["task_a"], "task-a")
        self.assertEqual(payload["conflicts"][0]["task_b"], "task-b")

    def test_check_conflicts_ignores_terminal_tasks(self) -> None:
        self.init_run()
        self.run_cli(
            "claim-files",
            "--repo",
            str(self.repo),
            "--run-id",
            "run",
            "--task-id",
            "task-a",
            "--agent",
            "codex-a",
            "--allow",
            "scripts/*",
        )
        self.run_cli(
            "claim-files",
            "--repo",
            str(self.repo),
            "--run-id",
            "run",
            "--task-id",
            "task-b",
            "--agent",
            "codex-b",
            "--allow",
            "scripts/codex_orch.py",
        )
        self.append_event({"type": "task_updated", "id": "task-b", "status": "complete"})

        result = self.run_cli("check-conflicts", "--repo", str(self.repo), "--run-id", "run")
        payload = json.loads(result.stdout)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["conflicts"], [])


if __name__ == "__main__":
    unittest.main()
