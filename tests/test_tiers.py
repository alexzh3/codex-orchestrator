from __future__ import annotations

from collections import Counter
import copy
import hashlib
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

from bench.adapters.tblite import TBLiteAdapter  # noqa: E402
from bench.run import load_tier_slots  # noqa: E402
from codex_orch import validate_benchmark_result  # noqa: E402


TIERS_PATH = ROOT / "bench" / "tiers.json"
TINY_IDS = [
    "book-portfolio-analysis",
    "corrupted-filesystem-recovery",
    "mech-system",
    "token-auth-websocket",
    "breast-cancer-mlflow",
    "service-deployment-wave-planner",
    "multi-labeller",
    "react-typescript-debugg",
    "bloom-filter-cache-penetration-prevention",
    "reproducibility-and-envsetup",
]
FRONTIER_IDS = {
    "terminalbench_2_1": [
        "torch-pipeline-parallelism",
        "torch-tensor-parallelism",
        "db-wal-recovery",
        "llm-inference-batching-scheduler",
        "query-optimize",
        "pytorch-model-recovery",
        "kv-store-grpc",
        "train-fasttext",
    ],
    "swebench_pro_public": [
        "instance_tutao__tutanota-da4edb7375c10f47f4ed3860a591c5e6557f7b5c-vbc0d9ba8f0071fbe982809910959a6ff8884dbbf",
        "instance_element-hq__element-web-33e8edb3d508d6eefb354819ca693b7accc695e7",
        "instance_flipt-io__flipt-e42da21a07a5ae35835ec54f74004ebd58713874",
    ],
    "rexbench": [
        "reasoning-or-reciting",
        "varierr-nli",
        "checkeval",
        "re-reading",
        "mission-impossible",
        "implicit-ins",
    ],
}


class TierBenchmarkTests(unittest.TestCase):
    def test_tiers_json_schema_v2_contents(self) -> None:
        payload = json.loads(TIERS_PATH.read_text(encoding="utf-8"))
        self.assertEqual(payload["schema_version"], 2)
        self.assertEqual(set(payload["tiers"]), {"tiny", "frontier"})

        tiny = payload["tiers"]["tiny"]
        self.assertEqual(len(tiny), 1)
        tiny_slot = tiny[0]
        self.assertEqual(tiny_slot["benchmark"], "tblite")
        self.assertEqual(tiny_slot["status"], "runnable")
        self.assertEqual([task["id"] for task in tiny_slot["tasks"]], TINY_IDS)
        for task in tiny_slot["tasks"]:
            self.assertIsInstance(task["reason"], str)
            self.assertTrue(task["reason"])
            self.assertRegex(task["sha256"], r"^[0-9a-f]{64}$")

        frontier = payload["tiers"]["frontier"]
        self.assertEqual(len(frontier), 3)
        status_by_benchmark = {slot["benchmark"]: (slot["status"], slot.get("issue")) for slot in frontier}
        self.assertEqual(
            status_by_benchmark,
            {
                "terminalbench_2_1": ("adapter_pending", "#18"),
                "swebench_pro_public": ("adapter_pending", "#18"),
                "rexbench": ("external_grading_only", "#10"),
            },
        )
        for slot in frontier:
            benchmark = slot["benchmark"]
            self.assertEqual([task["id"] for task in slot["tasks"]], FRONTIER_IDS[benchmark])
            for task in slot["tasks"]:
                self.assertIsInstance(task["reason"], str)
                self.assertTrue(task["reason"])
                if benchmark == "rexbench":
                    self.assertRegex(task["sha256"], r"^[0-9a-f]{64}$")
                else:
                    self.assertIsNone(task["sha256"])

    def test_tier_tiny_cli_dry_run_emits_schema_valid_frozen_ids(self) -> None:
        result = run_bench(
            "--tier",
            "tiny",
            "--plugin-ref",
            "demo",
            "--dry-run",
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        records = json_records(result.stdout)
        self.assertEqual(len(records), 10)
        self.assertEqual([record["case_id"] for record in records], TINY_IDS)
        for record in records:
            validate_benchmark_result(record)
            self.assertEqual(record["suite"], "tblite")
            self.assertEqual(record["plugin_ref"], "demo")
            self.assertEqual(record["external_score"]["selection"], "frozen")
        self.assertIn("selection=frozen", result.stderr)

    def test_tier_frontier_cli_dry_run_emits_schema_valid_frozen_ids(self) -> None:
        result = run_bench(
            "--tier",
            "frontier",
            "--plugin-ref",
            "demo",
            "--dry-run",
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        records = json_records(result.stdout)
        self.assertEqual(len(records), 17)
        counts = Counter(str(record["suite"]) for record in records)
        self.assertEqual(counts, Counter({"terminalbench_2_1": 8, "swebench_pro_public": 3, "rexbench": 6}))
        ids_by_benchmark: dict[str, list[str]] = {}
        for record in records:
            validate_benchmark_result(record)
            ids_by_benchmark.setdefault(str(record["suite"]), []).append(str(record["case_id"]))
            self.assertEqual(record["external_score"]["selection"], "frozen")
        self.assertEqual(ids_by_benchmark, FRONTIER_IDS)

    def test_compare_runs_on_two_tier_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            baseline = Path(tmp) / "baseline.jsonl"
            candidate = Path(tmp) / "candidate.jsonl"
            for plugin_ref, out_path in (("baseline", baseline), ("candidate", candidate)):
                run_result = run_bench(
                    "--tier",
                    "tiny",
                    "--plugin-ref",
                    plugin_ref,
                    "--dry-run",
                    "--out",
                    str(out_path),
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

    def test_dry_run_output_is_byte_identical_and_ignores_missing_descriptors(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            missing = Path(tmp) / "missing-tblite"
            first = Path(tmp) / "first.jsonl"
            second = Path(tmp) / "second.jsonl"
            env = dict(os.environ)
            env["TBLITE_DIR"] = str(missing)
            for out_path in (first, second):
                result = run_bench(
                    "--tier",
                    "tiny",
                    "--plugin-ref",
                    "demo",
                    "--dry-run",
                    "--out",
                    str(out_path),
                    env=env,
                )
                self.assertEqual(result.returncode, 0, result.stderr)

            self.assertEqual(first.read_bytes(), second.read_bytes())

    def test_frontier_real_mode_is_gated_without_results(self) -> None:
        result = run_bench(
            "--tier",
            "frontier",
            "--plugin-ref",
            "demo",
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(json_records(result.stdout), [])
        combined = result.stdout + result.stderr
        self.assertIn("GATED terminalbench_2_1: adapter_pending", combined)
        self.assertIn("#18", combined)
        self.assertIn("GATED swebench_pro_public: adapter_pending", combined)
        self.assertIn("GATED rexbench: external_grading_only", combined)
        self.assertIn("#10", combined)

    def test_resolve_frozen_tasks_real_mode_lists_missing_ids(self) -> None:
        adapter = TBLiteAdapter()
        with tempfile.TemporaryDirectory() as tmp:
            dataset_dir = Path(tmp)
            write_tblite_row(dataset_dir, "present-task")
            with patch.dict(os.environ, {adapter.dataset_env_var: str(dataset_dir)}):
                with self.assertRaises(RuntimeError) as error:
                    adapter.resolve_frozen_tasks(
                        [{"id": "missing-task", "reason": "missing", "sha256": None}],
                        dry_run=False,
                    )

        message = str(error.exception)
        self.assertIn("missing-task", message)
        self.assertIn(str(dataset_dir), message)
        self.assertIn(adapter.dataset_env_var, message)
        self.assertIn(adapter.issue_ref, message)

    def test_resolve_frozen_tasks_real_mode_rejects_hash_drift(self) -> None:
        adapter = TBLiteAdapter()
        with tempfile.TemporaryDirectory() as tmp:
            dataset_dir = Path(tmp)
            original = tblite_row("frozen-task", "Original instructions.")
            expected_hash = canonical_hash(original)
            tampered = dict(original)
            tampered["instructions"] = "Tampered instructions."
            write_rows(dataset_dir / "tasks.jsonl", [tampered])
            with patch.dict(os.environ, {adapter.dataset_env_var: str(dataset_dir)}):
                with self.assertRaises(RuntimeError) as error:
                    adapter.resolve_frozen_tasks(
                        [{"id": "frozen-task", "reason": "drift", "sha256": expected_hash}],
                        dry_run=False,
                    )

        message = str(error.exception)
        self.assertIn("frozen-task", message)
        self.assertIn("hash mismatch", message)
        self.assertIn(expected_hash, message)
        self.assertIn("descriptor content drifted", message)

    def test_load_tier_slots_validation_rejects_invalid_v2_payloads(self) -> None:
        payload = json.loads(TIERS_PATH.read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory() as tmp:
            temp_path = Path(tmp) / "tiers.json"

            duplicate = copy.deepcopy(payload)
            duplicate["tiers"]["tiny"][0]["tasks"][1]["id"] = duplicate["tiers"]["tiny"][0]["tasks"][0]["id"]
            temp_path.write_text(json.dumps(duplicate), encoding="utf-8")
            with self.assertRaises(ValueError):
                load_tier_slots("tiny", path=temp_path)

            missing_issue = copy.deepcopy(payload)
            missing_issue["tiers"]["frontier"][0].pop("issue")
            temp_path.write_text(json.dumps(missing_issue), encoding="utf-8")
            with self.assertRaises(ValueError):
                load_tier_slots("frontier", path=temp_path)

            schema_v1 = copy.deepcopy(payload)
            schema_v1["schema_version"] = 1
            temp_path.write_text(json.dumps(schema_v1), encoding="utf-8")
            with self.assertRaises(ValueError):
                load_tier_slots("tiny", path=temp_path)


def run_bench(*args: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "bench.run", *args],
        check=False,
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
    )


def json_records(stdout: str) -> list[dict[str, object]]:
    records: list[dict[str, object]] = []
    for line in stdout.splitlines():
        if line.startswith("{"):
            records.append(json.loads(line))
    return records


def tblite_row(task_id: str, instructions: str = "Solve the task.") -> dict[str, object]:
    return {
        "id": task_id,
        "instructions": instructions,
        "success_rate": 0.2,
        "acceptance": {"command": "true"},
        "files_allowed": ["README.md"],
    }


def write_tblite_row(dataset_dir: Path, task_id: str) -> None:
    write_rows(dataset_dir / "tasks.jsonl", [tblite_row(task_id)])


def write_rows(path: Path, records: list[dict[str, object]]) -> None:
    path.write_text("".join(json.dumps(record, sort_keys=True) + "\n" for record in records), encoding="utf-8")


def canonical_hash(record: dict[str, object]) -> str:
    payload = json.dumps(record, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


if __name__ == "__main__":
    unittest.main()
