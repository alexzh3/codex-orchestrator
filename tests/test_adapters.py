from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from bench.adapters.rexbench import RExBenchAdapter  # noqa: E402
from bench.adapters.swebench_verified_mini import SWEBenchVerifiedMiniAdapter  # noqa: E402
from bench.adapters.tblite import TBLiteAdapter  # noqa: E402
from codex_orch import validate_benchmark_result  # noqa: E402


ADAPTERS = (
    (RExBenchAdapter(), "tasks.jsonl", "id", "prompt"),
    (TBLiteAdapter(), "tasks.jsonl", "id", "instructions"),
    (SWEBenchVerifiedMiniAdapter(), "instances.jsonl", "instance_id", "problem_statement"),
)


class RealAdapterTests(unittest.TestCase):
    def write_dataset(
        self,
        root: Path,
        filename: str,
        id_field: str,
        prompt_field: str,
    ) -> None:
        records = [
            {
                id_field: "easy-task",
                prompt_field: "Solve the easier fake task.",
                "success_rate": 0.8,
                "acceptance": {"command": "true"},
                "files_allowed": ["README.md"],
            },
            {
                id_field: "hard-task",
                prompt_field: "Solve the harder fake task.",
                "success_rate": 0.1,
                "acceptance": {"command": "true"},
                "files_allowed": ["bench/README.md"],
            },
        ]
        (root / filename).write_text(
            "".join(json.dumps(record, sort_keys=True) + "\n" for record in records),
            encoding="utf-8",
        )

    def write_one_task_dataset(
        self,
        root: Path,
        filename: str,
        id_field: str,
        prompt_field: str,
    ) -> None:
        record = {
            id_field: "only-task",
            prompt_field: "Solve the only fake task.",
            "success_rate": 0.2,
            "acceptance": {"command": "true"},
            "files_allowed": ["README.md"],
        }
        (root / filename).write_text(json.dumps(record, sort_keys=True) + "\n", encoding="utf-8")

    def runner_result(self, task_id: str) -> dict[str, object]:
        return {
            "suite": "local-mini",
            "case_id": task_id,
            "plugin_ref": "demo",
            "repo_commit": "abc123",
            "passed": True,
            "wall_seconds": 0.25,
            "claude_turns": 3,
            "codex_sessions": 2,
            "codex_reviews": 1,
            "manual_interventions": 0,
            "prompt_log_pairs_complete": True,
            "ledger_errors": 0,
            "gate_passed": True,
            "report_score": 0.91,
            "external_score": {
                "tests_passed": True,
                "acceptance_command": "true",
                "acceptance_exit_code": 0,
                "acceptance_timed_out": False,
                "claude_exit_code": 0,
                "timed_out": False,
                "sidecar_present": True,
                "claude_argv": ["claude", "-p"],
            },
        }

    def test_iter_tasks_loads_real_dataset_and_selects_lowest_success_rate(self) -> None:
        for adapter, filename, id_field, prompt_field in ADAPTERS:
            with self.subTest(adapter=adapter.name), tempfile.TemporaryDirectory() as tmp:
                dataset_dir = Path(tmp)
                self.write_dataset(dataset_dir, filename, id_field, prompt_field)
                with patch.dict(os.environ, {adapter.dataset_env_var: str(dataset_dir)}):
                    tasks = adapter.iter_tasks(2, "lowest_success_rate", dry_run=False)

            self.assertEqual([task["id"] for task in tasks], ["hard-task", "easy-task"])
            self.assertEqual(tasks[0]["suite"], adapter.name)
            self.assertEqual(tasks[0]["benchmark"], adapter.name)
            self.assertEqual(tasks[0]["selection"], "lowest_success_rate")

    def test_iter_tasks_fails_when_real_dataset_cannot_fill_requested_count(self) -> None:
        for adapter, filename, id_field, prompt_field in ADAPTERS:
            with self.subTest(adapter=adapter.name), tempfile.TemporaryDirectory() as tmp:
                dataset_dir = Path(tmp)
                self.write_one_task_dataset(dataset_dir, filename, id_field, prompt_field)
                with patch.dict(os.environ, {adapter.dataset_env_var: str(dataset_dir)}):
                    with self.assertRaises(RuntimeError) as error:
                        adapter.iter_tasks(2, "lowest_success_rate", dry_run=False)

            self.assertNotIsInstance(error.exception, NotImplementedError)
            self.assertIn("requested count 2", str(error.exception))
            self.assertIn(adapter.dataset_env_var, str(error.exception))

    def test_explicit_empty_file_allowlist_is_preserved(self) -> None:
        adapter = RExBenchAdapter()
        task = {
            "id": "no-edits",
            "prompt": "Inspect only.",
            "selection": "lowest_success_rate",
            "files_allowed": [],
            "acceptance": {"command": "true"},
        }

        with tempfile.TemporaryDirectory() as tmp:
            case = adapter._case_from_task(task, Path(tmp))

        self.assertEqual(case["files_allowed"], [])

    def test_case_from_task_carries_target_repo_descriptor_fields(self) -> None:
        adapter = SWEBenchVerifiedMiniAdapter()
        with tempfile.TemporaryDirectory() as tmp:
            dataset_dir = Path(tmp) / "dataset"
            work_dir = Path(tmp) / "work"
            dataset_dir.mkdir()
            work_dir.mkdir()
            task = adapter._normalize_task(
                {
                    "instance_id": "swe-1",
                    "repo": "example/project",
                    "repo_url": "https://example.invalid/example/project.git",
                    "target_repo_path": "target-project",
                    "base_commit": "abc123",
                    "environment_setup_commit": "def456",
                    "problem_statement": "Fix the target repo.",
                    "acceptance": {"command": "true"},
                },
                dataset_dir,
                "lowest_success_rate",
            )
            case = adapter._case_from_task(task, work_dir)

        self.assertEqual(case["id"], "swe-1")
        self.assertEqual(case["instance_id"], "swe-1")
        self.assertEqual(case["repo"], "example/project")
        self.assertEqual(case["repo_url"], "https://example.invalid/example/project.git")
        self.assertEqual(case["target_repo_path"], str(dataset_dir / "target-project"))
        self.assertEqual(case["base_commit"], "abc123")
        self.assertEqual(case["start_ref"], "abc123")
        self.assertEqual(case["environment_setup_commit"], "def456")
        self.assertIs(case["requires_target_repo"], True)

    def test_adapter_passes_suite_to_run_claude_case(self) -> None:
        adapter = RExBenchAdapter()
        case = {
            "id": "suite-task",
            "suite": adapter.name,
            "start_ref": "main",
            "prompt": "Run the task.",
            "files_allowed": ["*"],
            "acceptance": {"command": "true"},
            "timeout_seconds": 1,
            "max_turns": 1,
            "max_budget_usd": 1,
        }

        with tempfile.TemporaryDirectory() as tmp:
            with patch("bench.adapters.base.run_claude_case", return_value=self.runner_result("suite-task")) as run_mock:
                adapter._run_claude_case(case, "demo", repo_root=ROOT, work_dir=Path(tmp))

        self.assertEqual(run_mock.call_args.kwargs["suite"], adapter.name)

    def test_run_task_uses_runner_and_grader_hooks_for_schema_valid_result(self) -> None:
        for adapter, filename, id_field, prompt_field in ADAPTERS:
            with self.subTest(adapter=adapter.name), tempfile.TemporaryDirectory() as tmp:
                temp_root = Path(tmp)
                dataset_dir = temp_root / "dataset"
                work_dir = temp_root / "work"
                dataset_dir.mkdir()
                work_dir.mkdir()
                self.write_dataset(dataset_dir, filename, id_field, prompt_field)
                with patch.dict(os.environ, {adapter.dataset_env_var: str(dataset_dir)}):
                    task = adapter.iter_tasks(1, "lowest_success_rate", dry_run=False)[0]

                with (
                    patch.object(adapter, "_run_claude_case", return_value=self.runner_result(str(task["id"]))) as run_mock,
                    patch.object(
                        adapter,
                        "_grade",
                        return_value={
                            "benchmark": adapter.name,
                            "tests_passed": True,
                            "grader_command": "fake-grader",
                        },
                    ) as grade_mock,
                ):
                    result = adapter.run_task(
                        task,
                        "demo",
                        dry_run=False,
                        repo_root=ROOT,
                        work_dir=work_dir,
                    )

                validate_benchmark_result(result)
                self.assertEqual(result["suite"], adapter.name)
                self.assertEqual(result["case_id"], "hard-task")
                self.assertTrue(result["passed"])
                self.assertEqual(result["plugin_ref"], "demo")
                external_score = result["external_score"]
                self.assertIsInstance(external_score, dict)
                self.assertTrue(external_score["run_claude_passed"])
                self.assertEqual(external_score["grader_command"], "fake-grader")

                case = run_mock.call_args.args[0]
                self.assertEqual(case["acceptance"], {"command": "true"})
                self.assertEqual(case["files_allowed"], ["bench/README.md"])
                grade_mock.assert_called_once()

    def test_timeout_and_grader_failure_merge_as_failed_results(self) -> None:
        adapter = RExBenchAdapter()
        task = {
            "id": "timeout-task",
            "prompt": "Trigger a timeout.",
            "selection": "lowest_success_rate",
            "acceptance": {"command": "true"},
        }

        timeout_runner = self.runner_result("timeout-task")
        timeout_runner["passed"] = False
        timeout_external = dict(timeout_runner["external_score"])
        timeout_external.pop("acceptance_exit_code")
        timeout_external["acceptance_timed_out"] = True
        timeout_runner["external_score"] = timeout_external

        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(adapter, "_run_claude_case", return_value=timeout_runner):
                timeout_result = adapter.run_task(
                    task,
                    "demo",
                    dry_run=False,
                    repo_root=ROOT,
                    work_dir=Path(tmp),
                )

        validate_benchmark_result(timeout_result)
        self.assertFalse(timeout_result["passed"])
        timeout_score = timeout_result["external_score"]
        self.assertIsInstance(timeout_score, dict)
        self.assertFalse(timeout_score["tests_passed"])
        self.assertTrue(timeout_score["grader_timed_out"])
        self.assertIsNone(timeout_score["grader_exit_code"])

        failing_runner = self.runner_result("timeout-task")
        failing_runner["passed"] = False
        failing_external = dict(failing_runner["external_score"])
        failing_external["acceptance_exit_code"] = 1
        failing_runner["external_score"] = failing_external

        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(adapter, "_run_claude_case", return_value=failing_runner):
                failing_result = adapter.run_task(
                    task,
                    "demo",
                    dry_run=False,
                    repo_root=ROOT,
                    work_dir=Path(tmp),
                )

        validate_benchmark_result(failing_result)
        self.assertFalse(failing_result["passed"])
        failing_score = failing_result["external_score"]
        self.assertIsInstance(failing_score, dict)
        self.assertFalse(failing_score["tests_passed"])
        self.assertEqual(failing_score["grader_exit_code"], 1)

    def test_missing_dataset_raises_clear_runtime_error(self) -> None:
        for adapter, _filename, _id_field, _prompt_field in ADAPTERS:
            with self.subTest(adapter=adapter.name), tempfile.TemporaryDirectory() as tmp:
                missing = Path(tmp) / "missing"
                with patch.dict(os.environ, {adapter.dataset_env_var: str(missing)}):
                    with self.assertRaises(RuntimeError) as error:
                        adapter.iter_tasks(1, "lowest_success_rate", dry_run=False)

            self.assertNotIsInstance(error.exception, NotImplementedError)
            message = str(error.exception)
            self.assertIn(adapter.dataset_env_var, message)
            self.assertIn(adapter.issue_ref, message)
            self.assertIn("Expected layout", message)


if __name__ == "__main__":
    unittest.main()
