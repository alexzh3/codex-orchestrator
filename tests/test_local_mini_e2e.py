from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from bench.runners.run_claude import (  # noqa: E402
    assemble_real_result,
    files_within_allowlist,
    load_case,
    run_case,
)
from codex_orch import validate_benchmark_result  # noqa: E402


CASE_DIR = ROOT / "bench" / "cases" / "local-mini"


class LocalMiniE2ETests(unittest.TestCase):
    def case_paths(self) -> list[Path]:
        return sorted(CASE_DIR.glob("*.json"))

    def test_case_loads_and_dry_run_result_validates(self) -> None:
        case_path = self.case_paths()[0]
        case = load_case(case_path)

        with tempfile.TemporaryDirectory() as tmp:
            first = run_case(case, "demo", dry_run=True, repo_root=ROOT, work_dir=Path(tmp))
            second = run_case(case, "demo", dry_run=True, repo_root=ROOT, work_dir=Path(tmp))

        self.assertEqual(case["suite"], "local-mini")
        self.assertEqual(first, second)
        validate_benchmark_result(first)
        schema = json.loads((ROOT / "schemas" / "benchmark-result.schema.json").read_text(encoding="utf-8"))
        self.assertEqual(set(first), set(schema["properties"]))

    def test_dry_run_exposes_claude_argv(self) -> None:
        case = load_case(self.case_paths()[0])

        with tempfile.TemporaryDirectory() as tmp:
            result = run_case(case, "feature/ref", dry_run=True, repo_root=ROOT, work_dir=Path(tmp))

        external_score = result["external_score"]
        self.assertIsInstance(external_score, dict)
        argv = external_score["claude_argv"]
        self.assertIn("--plugin-dir", argv)
        self.assertIn("--permission-mode", argv)
        self.assertEqual(argv[argv.index("--permission-mode") + 1], "bypassPermissions")
        self.assertNotIn("--max-turns", argv)
        self.assertIn("--max-budget-usd", argv)
        self.assertIn(str(case["max_budget_usd"]), argv)
        self.assertIn(f"/codex-orchestrator:workflow {case['prompt']}", argv)

    def test_files_within_allowlist_reports_offending_paths(self) -> None:
        ok, offending = files_within_allowlist(["README.md", "scripts/x.py"], ["README.md"])

        self.assertFalse(ok)
        self.assertEqual(offending, ["scripts/x.py"])

        ok, offending = files_within_allowlist(["README.md", "scripts/x.py"], ["README.md", "scripts/*.py"])

        self.assertTrue(ok)
        self.assertEqual(offending, [])

    def test_missing_sidecar_real_payload_fails_visibly(self) -> None:
        case = load_case(self.case_paths()[0])
        payload = assemble_real_result(
            case,
            "demo",
            repo_commit="abc123",
            wall_seconds=0.1,
            sidecar={},
            sidecar_path=None,
            sidecar_error="missing .codex-orchestrator run directory",
            acceptance_command="true",
            acceptance_returncode=0,
            acceptance_timed_out=False,
            claude_returncode=0,
            timed_out=False,
            claude_argv=["claude", "-p"],
            changed_paths=[],
            forbidden_paths=[],
        )

        validate_benchmark_result(payload)
        self.assertFalse(payload["passed"])
        self.assertEqual(payload["ledger_errors"], 1)
        self.assertEqual(payload["report_score"], 0.0)
        external_score = payload["external_score"]
        self.assertIsInstance(external_score, dict)
        self.assertFalse(external_score["sidecar_present"])
        self.assertIn("missing sidecar", external_score["failure_reason"])

    def test_forbidden_changed_file_fails_even_when_acceptance_passes(self) -> None:
        case = load_case(self.case_paths()[0])
        payload = assemble_real_result(
            case,
            "demo",
            repo_commit="abc123",
            wall_seconds=0.1,
            sidecar={
                "suite": "local-mini",
                "case_id": case["id"],
                "plugin_ref": "demo",
                "repo_commit": "abc123",
                "passed": True,
                "wall_seconds": 0.1,
                "claude_turns": 3,
                "codex_sessions": 2,
                "codex_reviews": 1,
                "manual_interventions": 0,
                "prompt_log_pairs_complete": True,
                "ledger_errors": 0,
                "gate_passed": True,
                "report_score": 0.91,
                "external_score": {"tests_passed": True},
            },
            sidecar_path=Path("/tmp/benchmark.json"),
            sidecar_error=None,
            acceptance_command="true",
            acceptance_returncode=0,
            acceptance_timed_out=False,
            claude_returncode=0,
            timed_out=False,
            claude_argv=["claude", "-p"],
            changed_paths=["README.md", "scripts/x.py"],
            forbidden_paths=["scripts/x.py"],
        )

        validate_benchmark_result(payload)
        self.assertFalse(payload["passed"])
        external_score = payload["external_score"]
        self.assertIsInstance(external_score, dict)
        self.assertTrue(external_score["tests_passed"])
        self.assertTrue(external_score["forbidden_file_violation"])
        self.assertEqual(external_score["forbidden_files"], ["scripts/x.py"])

    def test_cli_local_mini_dry_run_writes_case_repeat_results(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out_path = Path(tmp) / "local-mini.jsonl"
            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "bench.run",
                    "--suite",
                    "local-mini",
                    "--plugin-ref",
                    "demo",
                    "--dry-run",
                    "--repeats",
                    "2",
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
            records = [json.loads(line) for line in out_path.read_text(encoding="utf-8").splitlines()]

        self.assertEqual(len(records), len(self.case_paths()) * 2)
        for record in records:
            validate_benchmark_result(record)
            self.assertEqual(record["suite"], "local-mini")
            self.assertEqual(record["plugin_ref"], "demo")

    def test_cli_stdout_and_compare_two_dry_run_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            stdout_result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "bench.run",
                    "--suite",
                    "local-mini",
                    "--plugin-ref",
                    "stdout-demo",
                    "--dry-run",
                ],
                check=False,
                cwd=ROOT,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            self.assertEqual(stdout_result.returncode, 0, stdout_result.stderr)
            stdout_records = [json.loads(line) for line in stdout_result.stdout.splitlines()]
            self.assertEqual(len(stdout_records), len(self.case_paths()))

            baseline = Path(tmp) / "baseline.jsonl"
            candidate = Path(tmp) / "candidate.jsonl"
            for plugin_ref, path in (("baseline", baseline), ("candidate", candidate)):
                run_result = subprocess.run(
                    [
                        sys.executable,
                        "-m",
                        "bench.run",
                        "--suite",
                        "local-mini",
                        "--plugin-ref",
                        plugin_ref,
                        "--dry-run",
                        "--out",
                        str(path),
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


if __name__ == "__main__":
    unittest.main()
