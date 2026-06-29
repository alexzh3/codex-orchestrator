from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

from bench.runners.run_claude import load_case as load_local_mini_case
from bench.runners.run_claude import run_case as run_local_mini_case
from bench.runners.run_replay import run_case as run_replay_case


ROOT = Path(__file__).resolve().parents[1]
CASE_ROOT = ROOT / "bench" / "cases"
DRY_RUN_WORK_DIR = Path("/tmp/codex-orch-local-mini-dry-run")


def discover_cases(suite: str) -> list[Path]:
    suite_dir = CASE_ROOT / suite
    if not suite_dir.is_dir():
        return []
    if suite == "local-mini":
        return sorted(path for path in suite_dir.iterdir() if path.suffix == ".json")
    return sorted(path for path in suite_dir.iterdir() if (path / "case.json").is_file())


def positive_int(value: str) -> int:
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("value must be at least 1")
    return parsed


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run Codex Orchestrator benchmark suites.")
    parser.add_argument("--suite", required=True, choices=("replay", "local-mini"), help="Benchmark suite to run.")
    parser.add_argument("--plugin-ref", help="Plugin git ref or directory for local-mini.")
    parser.add_argument("--dry-run", action="store_true", help="Run local-mini without invoking Claude or Codex.")
    parser.add_argument("--repeats", type=positive_int, default=1, help="Number of local-mini repeats.")
    parser.add_argument("--update-golden", action="store_true", help="Rewrite golden reports.")
    parser.add_argument("--out", help="Write benchmark-result records as JSONL.")
    return parser


def write_jsonl(path: Path, results: list[dict[str, object]]) -> None:
    path.write_text(
        "".join(json.dumps(result, sort_keys=True) + "\n" for result in results),
        encoding="utf-8",
    )


def run_replay_suite(args: argparse.Namespace, cases: list[Path]) -> int:
    results: list[dict[str, object]] = []
    failures = 0
    for case_dir in cases:
        try:
            result = run_replay_case(case_dir, update_golden=args.update_golden)
        except Exception as exc:  # pragma: no cover - exercised by CLI failure paths.
            failures += 1
            print(f"FAIL {args.suite}/{case_dir.name}: {exc}")
            continue

        results.append(result.payload)
        passed = bool(result.payload.get("passed"))
        status = "PASS" if passed else "FAIL"
        if not passed:
            failures += 1
        print(
            f"{status} {args.suite}/{result.payload.get('case_id')} "
            f"report_score={float(result.payload.get('report_score', 0.0)):.2f} "
            f"wall_seconds={float(result.payload.get('wall_seconds', 0.0)):.4f}"
        )

    if args.out:
        write_jsonl(Path(args.out), results)

    total = len(cases)
    print(f"Summary: {total - failures}/{total} passed")
    return 1 if failures else 0


def run_local_mini_suite(args: argparse.Namespace, cases: list[Path]) -> int:
    if not args.plugin_ref:
        raise SystemExit("--plugin-ref is required for --suite local-mini")

    results: list[dict[str, object]] = []
    hard_failures = 0
    summary_stream = sys.stdout if args.out else sys.stderr

    def run_cases(work_dir: Path) -> None:
        nonlocal hard_failures
        for repeat in range(1, args.repeats + 1):
            for case_path in cases:
                try:
                    case = load_local_mini_case(case_path)
                    result = run_local_mini_case(
                        case,
                        args.plugin_ref,
                        dry_run=args.dry_run,
                        repo_root=ROOT,
                        work_dir=work_dir,
                    )
                except Exception as exc:  # pragma: no cover - exercised by CLI failure paths.
                    hard_failures += 1
                    print(f"ERROR local-mini/{case_path.stem} repeat={repeat}: {exc}", file=summary_stream)
                    continue

                results.append(result)
                status = "PASS" if result.get("passed") is True else "FAIL"
                print(
                    f"{status} local-mini/{result.get('case_id')} repeat={repeat} "
                    f"report_score={float(result.get('report_score', 0.0)):.2f} "
                    f"gate_passed={result.get('gate_passed')} "
                    f"ledger_errors={result.get('ledger_errors')}",
                    file=summary_stream,
                )

    if args.dry_run:
        run_cases(DRY_RUN_WORK_DIR)
    else:
        with tempfile.TemporaryDirectory(prefix="codex-orch-local-mini-") as temp_root:
            run_cases(Path(temp_root))

    if args.out:
        write_jsonl(Path(args.out), results)
    else:
        for result in results:
            print(json.dumps(result, sort_keys=True))

    total = len(cases) * args.repeats
    external_passes = sum(1 for result in results if result.get("passed") is True)
    print(
        f"Summary: {external_passes}/{len(results)} external passed, "
        f"hard_failures={hard_failures}, expected_runs={total}",
        file=summary_stream,
    )
    return 1 if hard_failures else 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    cases = discover_cases(args.suite)
    if not cases:
        print(f"No benchmark cases found for suite {args.suite}", file=sys.stderr)
        return 1
    if args.suite == "local-mini":
        return run_local_mini_suite(args, cases)
    return run_replay_suite(args, cases)


if __name__ == "__main__":
    raise SystemExit(main())
