from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from bench import prepare_datasets  # noqa: E402


class PrepareDatasetsTests(unittest.TestCase):
    def test_swebench_converter_filters_and_ranks_hardest_first(self) -> None:
        rows = [
            {
                "repo": "django/django",
                "instance_id": "django__django-11790",
                "base_commit": "abc123",
                "environment_setup_commit": "env123",
                "problem_statement": "Fix a Django regression.",
                "FAIL_TO_PASS": ["tests.fail"],
                "PASS_TO_PASS": ["tests.pass"],
                "difficulty": "15 min - 1 hour",
            },
            {
                "repo": "example/project",
                "instance_id": "example__project-999",
                "base_commit": "hard123",
                "environment_setup_commit": "env999",
                "problem_statement": "Fix the hard regression.",
                "FAIL_TO_PASS": ["tests.hard"],
                "PASS_TO_PASS": ["tests.stable"],
                "difficulty": ">4 hours",
            },
            {
                "repo": "example/project",
                "instance_id": "example__project-100",
                "base_commit": "easy123",
                "environment_setup_commit": "env100",
                "problem_statement": "Fix the easy regression.",
                "FAIL_TO_PASS": ["tests.easy"],
                "PASS_TO_PASS": ["tests.stable"],
                "difficulty": "<15 min fix",
            },
            {
                "repo": "example/project",
                "instance_id": "example__project-400",
                "base_commit": "mediumhard123",
                "environment_setup_commit": "env400",
                "problem_statement": "Fix the one-hour-plus regression.",
                "FAIL_TO_PASS": ["tests.mediumhard"],
                "PASS_TO_PASS": ["tests.stable"],
                "difficulty": "1-4 hours",
            },
        ]

        self.assertEqual(prepare_datasets.swebench_difficulty_score(">4 hours"), 5.0)
        self.assertEqual(prepare_datasets.swebench_difficulty_score("1-4 hours"), 4.0)
        self.assertEqual(prepare_datasets.swebench_difficulty_score("15 min - 1 hour"), 3.0)
        self.assertEqual(prepare_datasets.swebench_difficulty_score("<15 min fix"), 1.0)

        tasks = prepare_datasets.convert_swebench_rows(rows)

        self.assertEqual(
            [task["instance_id"] for task in tasks],
            ["example__project-999", "example__project-400"],
        )
        self.assertEqual(tasks[0]["difficulty_score"], 5.0)
        self.assertEqual(tasks[1]["difficulty_score"], 4.0)
        self.assertEqual(tasks[0]["files_allowed"], ["*", "**/*"])
        self.assertIn("SWE-bench Docker harness", tasks[0]["grader_command"])

        parsed = [json.loads(line) for line in prepare_datasets.jsonl_text(tasks).splitlines()]
        self.assertEqual(parsed[0]["instance_id"], "example__project-999")
        for field in (
            "instance_id",
            "repo",
            "base_commit",
            "environment_setup_commit",
            "problem_statement",
            "FAIL_TO_PASS",
            "PASS_TO_PASS",
            "difficulty",
            "difficulty_score",
            "files_allowed",
            "grader_command",
        ):
            self.assertIn(field, parsed[0])

    @unittest.skipUnless(prepare_datasets.tomllib is not None, "tomllib requires Python 3.11+")
    def test_tblite_converter_maps_difficulty_and_ranks_by_time(self) -> None:
        task_toml = """
[metadata]
difficulty = "medium"
expert_time_estimate_min = 70
category = "debugging"
tags = ["python", "tests"]

[verifier]
timeout_sec = 600
"""
        raw_tasks = [
            ("medium-short", task_toml.replace("70", "30"), "Short task instructions."),
            ("medium-long", task_toml, "Long task instructions."),
        ]

        tasks = prepare_datasets.convert_tblite_tasks(raw_tasks)

        self.assertEqual([task["id"] for task in tasks], ["medium-long", "medium-short"])
        self.assertEqual(tasks[0]["difficulty"], "medium")
        self.assertEqual(tasks[0]["difficulty_score"], 3.0)
        self.assertEqual(tasks[0]["expert_time_estimate_min"], 70.0)
        self.assertEqual(tasks[0]["category"], "debugging")
        self.assertEqual(tasks[0]["tags"], ["python", "tests"])
        self.assertEqual(tasks[0]["timeout_seconds"], 600)
        self.assertEqual(tasks[0]["prompt"], "Long task instructions.")
        self.assertEqual(tasks[0]["files_allowed"], ["*", "**/*"])
        self.assertIn("OpenThoughts-TBLite", tasks[0]["grader_command"])
        self.assertEqual(tasks[0]["tblite_task_dir"], "medium-long")

        parsed = [json.loads(line) for line in prepare_datasets.jsonl_text(tasks).splitlines()]
        self.assertEqual(parsed[0]["id"], "medium-long")

    def test_rexbench_converter_emits_descriptor_shape(self) -> None:
        task = prepare_datasets.convert_rexbench_task(
            "rex-task-01",
            "Implement the experiment described here.",
            "dataset/rex-task-01",
        )

        self.assertEqual(task["id"], "rex-task-01")
        self.assertEqual(task["prompt"], "Implement the experiment described here.")
        self.assertEqual(task["target_repo_path"], "dataset/rex-task-01")
        self.assertIsNone(task["difficulty_score"])
        self.assertEqual(task["files_allowed"], ["*", "**/*"])
        self.assertIn("RExBench executor", task["grader_command"])

        parsed = json.loads(prepare_datasets.jsonl_text([task]).strip())
        self.assertEqual(parsed["id"], "rex-task-01")

    def test_gitignore_excludes_prepared_datasets(self) -> None:
        gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
        self.assertIn("bench/datasets/", gitignore)


if __name__ == "__main__":
    unittest.main()
