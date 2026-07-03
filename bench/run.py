"""Replay self-test runner; external benchmarks live in the codex-orchestrator-bench repo."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from bench.runners.run_replay import run_case as run_replay_case


ROOT = Path(__file__).resolve().parents[1]
CASE_ROOT = ROOT / "bench" / "cases"


def discover_cases(suite: str) -> list[Path]:
    suite_dir = CASE_ROOT / suite
    if not suite_dir.is_dir():
        return []
    return sorted(path for path in suite_dir.iterdir() if (path / "case.json").is_file())


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run Codex Orchestrator replay self-tests.")
    parser.add_argument("--suite", choices=("replay",), default="replay", help="Benchmark suite to run.")
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


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    cases = discover_cases(args.suite)
    if not cases:
        print(f"No benchmark cases found for suite {args.suite}", file=sys.stderr)
        return 1
    return run_replay_suite(args, cases)


if __name__ == "__main__":
    raise SystemExit(main())
