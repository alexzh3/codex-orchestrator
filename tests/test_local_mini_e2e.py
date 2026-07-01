from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from bench.runners.run_claude import (  # noqa: E402
    TARGET_REPO_CACHE_ENV,
    _generate_benchmark_sidecar,
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

    def git(self, repo: Path, *args: str) -> str:
        result = subprocess.run(
            ["git", *args],
            check=True,
            cwd=repo,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        return result.stdout.strip()

    def init_target_repo(self, repo: Path) -> str:
        self.git(repo, "init")
        self.git(repo, "config", "user.email", "bench@example.invalid")
        self.git(repo, "config", "user.name", "Bench Test")
        (repo / "TARGET_MARKER").write_text("target\n", encoding="utf-8")
        self.git(repo, "add", "TARGET_MARKER")
        self.git(repo, "commit", "-m", "initial target")
        return self.git(repo, "rev-parse", "HEAD")

    def test_case_loads_and_dry_run_result_validates(self) -> None:
        case_path = self.case_paths()[0]
        case = load_case(case_path)

        with tempfile.TemporaryDirectory() as tmp:
            first = run_case(case, "demo", dry_run=True, repo_root=ROOT, work_dir=Path(tmp))
            second = run_case(case, "demo", dry_run=True, repo_root=ROOT, work_dir=Path(tmp))

        self.assertEqual(case["suite"], "local-mini")
        self.assertEqual(first, second)
        validate_benchmark_result(first)
        schema = json.loads((ROOT / "bench" / "schemas" / "benchmark-result.schema.json").read_text(encoding="utf-8"))
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
        # Claude exposes no --max-turns flag; max_turns only bounds the dry-run simulation.
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

    def test_external_real_payload_checks_out_declared_target_repo(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            temp_root = Path(tmp)
            target_repo = temp_root / "target-repo"
            work_dir = temp_root / "work"
            target_repo.mkdir()
            work_dir.mkdir()
            target_commit = self.init_target_repo(target_repo)
            case = {
                "id": "external-target",
                "suite": "rexbench",
                "requires_target_repo": True,
                "target_repo_path": str(target_repo),
                "base_commit": target_commit,
                "start_ref": "main",
                "prompt": "Touch only the target repo.",
                "files_allowed": ["*"],
                "acceptance": {"command": "test -f TARGET_MARKER"},
                "timeout_seconds": 30,
                "max_turns": 1,
                "max_budget_usd": 1,
            }
            real_run = subprocess.run
            claude_cwds: list[Path] = []
            marker_values: list[str] = []

            def fake_run(args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
                if isinstance(args, list) and args and args[0] == "claude":
                    cwd = Path(kwargs["cwd"])
                    claude_cwds.append(cwd)
                    marker_values.append((cwd / "TARGET_MARKER").read_text(encoding="utf-8"))
                    self.assertNotEqual(cwd.resolve(), ROOT.resolve())
                    return subprocess.CompletedProcess(args, 0, "", "")
                return real_run(args, **kwargs)

            with patch("bench.runners.run_claude.subprocess.run", side_effect=fake_run):
                result = run_case(
                    case,
                    str(ROOT),
                    dry_run=False,
                    repo_root=ROOT,
                    work_dir=work_dir,
                    suite="rexbench",
                )

        validate_benchmark_result(result)
        self.assertEqual(result["suite"], "rexbench")
        self.assertEqual(result["repo_commit"], target_commit)
        self.assertEqual(len(claude_cwds), 1)
        self.assertEqual(marker_values, ["target\n"])
        external_score = result["external_score"]
        self.assertIsInstance(external_score, dict)
        self.assertEqual(external_score["acceptance_exit_code"], 0)

    def test_external_real_payload_refuses_unresolved_target_repo(self) -> None:
        case = {
            "id": "missing-target",
            "suite": "swebench_verified_mini",
            "requires_target_repo": True,
            "repo": "example/missing",
            "base_commit": "abc123",
            "start_ref": "main",
            "prompt": "Fix the missing target.",
            "files_allowed": ["*"],
            "acceptance": {"command": "true"},
            "timeout_seconds": 30,
            "max_turns": 1,
            "max_budget_usd": 1,
        }

        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict("os.environ", {TARGET_REPO_CACHE_ENV: ""}):
                with self.assertRaises(NotImplementedError) as error:
                    run_case(
                        case,
                        str(ROOT),
                        dry_run=False,
                        repo_root=ROOT,
                        work_dir=Path(tmp),
                        suite="swebench_verified_mini",
                    )

        message = str(error.exception)
        self.assertIn("target repo", message)
        self.assertIn("example/missing", message)
        self.assertIn(TARGET_REPO_CACHE_ENV, message)

    def test_benchmark_sidecar_uses_requested_suite_and_local_mini_default(self) -> None:
        calls: list[list[str]] = []

        def write_sidecar_for_call(args: object, **_kwargs: object) -> subprocess.CompletedProcess[str]:
            self.assertIsInstance(args, list)
            argv = [str(value) for value in args]
            calls.append(argv)
            run_id = argv[argv.index("--run-id") + 1]
            suite = argv[argv.index("--suite") + 1]
            case_id = argv[argv.index("--case-id") + 1]
            plugin_ref = argv[argv.index("--plugin-ref") + 1]
            target_dir = Path(argv[argv.index("--repo") + 1])
            sidecar = {
                "suite": suite,
                "case_id": case_id,
                "plugin_ref": plugin_ref,
                "repo_commit": "abc123",
                "passed": True,
                "wall_seconds": 0.1,
                "claude_turns": 1,
                "codex_sessions": 1,
                "codex_reviews": 0,
                "manual_interventions": 0,
                "prompt_log_pairs_complete": True,
                "ledger_errors": 0,
                "gate_passed": True,
                "report_score": 0.9,
                "external_score": {"tests_passed": True},
            }
            (target_dir / ".codex-orchestrator" / "runs" / run_id / "benchmark.json").write_text(
                json.dumps(sidecar, sort_keys=True),
                encoding="utf-8",
            )
            return subprocess.CompletedProcess(args, 0, "", "")

        with tempfile.TemporaryDirectory() as tmp:
            temp_root = Path(tmp)
            external_target = temp_root / "external"
            external_run = external_target / ".codex-orchestrator" / "runs" / "run-external"
            external_run.mkdir(parents=True)
            local_target = temp_root / "local"
            local_run = local_target / ".codex-orchestrator" / "runs" / "run-local"
            local_run.mkdir(parents=True)

            with patch("bench.runners.run_claude.subprocess.run", side_effect=write_sidecar_for_call):
                external_path, external_error = _generate_benchmark_sidecar(
                    target_dir=external_target,
                    plugin_dir=ROOT,
                    case_id="external-case",
                    plugin_ref="demo",
                    timeout_seconds=30,
                    suite="rexbench",
                )
                local_path, local_error = _generate_benchmark_sidecar(
                    target_dir=local_target,
                    plugin_dir=ROOT,
                    case_id="local-case",
                    plugin_ref="demo",
                    timeout_seconds=30,
                )

            self.assertIsNone(external_error)
            self.assertIsNone(local_error)
            self.assertIsNotNone(external_path)
            self.assertIsNotNone(local_path)
            external_suite = json.loads(external_path.read_text(encoding="utf-8"))["suite"]
            local_suite = json.loads(local_path.read_text(encoding="utf-8"))["suite"]

        self.assertEqual(external_suite, "rexbench")
        self.assertEqual(local_suite, "local-mini")
        self.assertEqual(calls[0][calls[0].index("--suite") + 1], "rexbench")
        self.assertEqual(calls[1][calls[1].index("--suite") + 1], "local-mini")

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
