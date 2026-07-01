from __future__ import annotations

from collections import Counter
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from bench.adapters import ADAPTERS  # noqa: E402
from codex_orch import validate_benchmark_result  # noqa: E402


TIERS_PATH = ROOT / "bench" / "tiers.json"


class TierBenchmarkTests(unittest.TestCase):
    def test_tiers_json_counts(self) -> None:
        payload = json.loads(TIERS_PATH.read_text(encoding="utf-8"))
        self.assertEqual(payload["selection_default"], "lowest_success_rate")

        tiers = payload["tiers"]
        self.assertEqual(sum(slot["count"] for slot in tiers["tiny"]), 13)
        self.assertEqual(sum(slot["count"] for slot in tiers["normal"]), 28)
        self.assertEqual(
            Counter({slot["benchmark"]: slot["count"] for slot in tiers["tiny"]}),
            Counter({"rexbench": 3, "tblite": 10}),
        )
        self.assertEqual(
            Counter({slot["benchmark"]: slot["count"] for slot in tiers["normal"]}),
            Counter({"rexbench": 6, "tblite": 15, "swebench_verified_mini": 7}),
        )

    def test_tier_tiny_cli_dry_run_emits_schema_valid_counts(self) -> None:
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "bench.run",
                "--tier",
                "tiny",
                "--plugin-ref",
                "demo",
                "--dry-run",
            ],
            check=False,
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        records = [json.loads(line) for line in result.stdout.splitlines()]
        self.assertEqual(len(records), 13)
        counts: Counter[str] = Counter()
        for record in records:
            validate_benchmark_result(record)
            counts[str(record["suite"])] += 1
            self.assertEqual(record["plugin_ref"], "demo")
        self.assertEqual(counts, Counter({"rexbench": 3, "tblite": 10}))
        self.assertIn("Summary rexbench: ", result.stderr)
        self.assertIn("Summary total: ", result.stderr)

    def test_adapter_dry_run_argv_contains_plugin_dir_and_workflow_prompt(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            for adapter in ADAPTERS.values():
                task = adapter.iter_tasks(1, "lowest_success_rate", dry_run=True)[0]
                result = adapter.run_task(
                    task,
                    "demo",
                    dry_run=True,
                    repo_root=ROOT,
                    work_dir=Path(tmp),
                )

                validate_benchmark_result(result)
                external_score = result["external_score"]
                self.assertIsInstance(external_score, dict)
                argv = external_score["claude_argv"]
                self.assertIn("--plugin-dir", argv)
                self.assertIn(f"/codex-orchestrator:workflow {task['prompt']}", argv)

    def test_compare_runs_on_two_tier_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            baseline = Path(tmp) / "baseline.jsonl"
            candidate = Path(tmp) / "candidate.jsonl"
            for plugin_ref, out_path in (("baseline", baseline), ("candidate", candidate)):
                run_result = subprocess.run(
                    [
                        sys.executable,
                        "-m",
                        "bench.run",
                        "--tier",
                        "tiny",
                        "--plugin-ref",
                        plugin_ref,
                        "--dry-run",
                        "--out",
                        str(out_path),
                    ],
                    check=False,
                    cwd=ROOT,
                    text=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                )
                self.assertEqual(run_result.returncode, 0, run_result.stderr)

            compare = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "bench.compare",
                    "--baseline",
                    str(baseline),
                    "--candidate",
                    str(candidate),
                ],
                check=False,
                cwd=ROOT,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

        self.assertEqual(compare.returncode, 0, compare.stderr)
        self.assertIn("Benchmark comparison", compare.stdout)
        self.assertIn("external pass rate", compare.stdout)

    def test_real_mode_adapter_methods_raise_runtime_error(self) -> None:
        for adapter in ADAPTERS.values():
            with self.subTest(adapter=adapter.name), tempfile.TemporaryDirectory() as tmp:
                empty_dataset_dir = Path(tmp)
                with patch.dict(os.environ, {adapter.dataset_env_var: str(empty_dataset_dir)}):
                    with self.assertRaises(RuntimeError) as selection_error:
                        adapter.iter_tasks(1, "lowest_success_rate", dry_run=False)
                    self.assertNotIsInstance(selection_error.exception, NotImplementedError)
                    self.assertIn(adapter.real_infra, str(selection_error.exception))

                    task = adapter.iter_tasks(1, "lowest_success_rate", dry_run=True)[0]
                    with self.assertRaises(RuntimeError) as run_error:
                        adapter.run_task(
                            task,
                            "demo",
                            dry_run=False,
                            repo_root=ROOT,
                            work_dir=Path("/tmp/codex-orch-tier-test"),
                        )
                    self.assertNotIsInstance(run_error.exception, NotImplementedError)
                    self.assertIn(adapter.real_infra, str(run_error.exception))

    def test_dry_run_output_is_byte_identical(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            first = Path(tmp) / "first.jsonl"
            second = Path(tmp) / "second.jsonl"
            for out_path in (first, second):
                result = subprocess.run(
                    [
                        sys.executable,
                        "-m",
                        "bench.run",
                        "--tier",
                        "tiny",
                        "--plugin-ref",
                        "demo",
                        "--dry-run",
                        "--out",
                        str(out_path),
                    ],
                    check=False,
                    cwd=ROOT,
                    text=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                )
                self.assertEqual(result.returncode, 0, result.stderr)

            self.assertEqual(first.read_bytes(), second.read_bytes())


if __name__ == "__main__":
    unittest.main()
