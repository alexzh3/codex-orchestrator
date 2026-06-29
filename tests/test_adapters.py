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
