from __future__ import annotations

import argparse
from collections import Counter
import json
import sys
import tempfile
from pathlib import Path

from bench.runners.run_claude import load_case as load_local_mini_case
from bench.runners.run_claude import run_case as run_local_mini_case
from bench.runners.run_replay import run_case as run_replay_case
from bench.adapters import get_adapter


ROOT = Path(__file__).resolve().parents[1]
CASE_ROOT = ROOT / "bench" / "cases"
TIERS_PATH = ROOT / "bench" / "tiers.json"
DRY_RUN_WORK_DIR = Path("/tmp/codex-orch-local-mini-dry-run")
TIER_DRY_RUN_WORK_DIR = Path("/tmp/codex-orch-tier-dry-run")


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
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--suite", choices=("replay", "local-mini"), help="Benchmark suite to run.")
    target.add_argument("--tier", choices=("tiny", "normal"), help="Head-to-head benchmark tier to run.")
    parser.add_argument("--plugin-ref", help="Plugin git ref or directory for local-mini or tier runs.")
    parser.add_argument("--dry-run", action="store_true", help="Run without invoking external benchmark infra.")
    parser.add_argument("--repeats", type=positive_int, default=1, help="Number of local-mini or tier repeats.")
    parser.add_argument("--update-golden", action="store_true", help="Rewrite golden reports.")
    parser.add_argument("--out", help="Write benchmark-result records as JSONL.")
    return parser


def write_jsonl(path: Path, results: list[dict[str, object]]) -> None:
    path.write_text(
        "".join(json.dumps(result, sort_keys=True) + "\n" for result in results),
        encoding="utf-8",
    )


def load_tier_slots(tier: str) -> list[dict[str, object]]:
    payload = json.loads(TIERS_PATH.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{TIERS_PATH} must contain a JSON object")
    selection_default = payload.get("selection_default")
    if not isinstance(selection_default, str) or not selection_default:
        raise ValueError(f"{TIERS_PATH} is missing selection_default")
    tiers = payload.get("tiers")
    if not isinstance(tiers, dict):
        raise ValueError(f"{TIERS_PATH} is missing tiers")
    raw_slots = tiers.get(tier)
    if not isinstance(raw_slots, list):
        raise ValueError(f"{TIERS_PATH} is missing tier {tier!r}")

    slots: list[dict[str, object]] = []
    for index, raw_slot in enumerate(raw_slots, start=1):
        if not isinstance(raw_slot, dict):
            raise ValueError(f"{tier} slot {index} must be an object")
        benchmark = raw_slot.get("benchmark")
        count = raw_slot.get("count")
        selection = raw_slot.get("selection", selection_default)
        if not isinstance(benchmark, str) or not benchmark:
            raise ValueError(f"{tier} slot {index} is missing benchmark")
        if type(count) is not int or count < 1:
            raise ValueError(f"{tier} slot {index} count must be a positive integer")
        if not isinstance(selection, str) or not selection:
            raise ValueError(f"{tier} slot {index} selection must be a non-empty string")
        slots.append({"benchmark": benchmark, "count": count, "selection": selection})
    return slots


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
        if args.dry_run:
            args.plugin_ref = "dry-run"
        else:
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


def real_mode_error(benchmark: str, infra: str, exc: NotImplementedError) -> str:
    return f"real {benchmark} runs require {infra}; use --dry-run or implement the adapter (issue #N): {exc}"


def run_tier(args: argparse.Namespace) -> int:
    if not args.plugin_ref:
        raise SystemExit("--plugin-ref is required for --tier")

    slots = load_tier_slots(args.tier)
    results: list[dict[str, object]] = []
    hard_failures = 0
    expected_runs = sum(int(slot["count"]) for slot in slots) * args.repeats
    per_benchmark_total: Counter[str] = Counter()
    per_benchmark_passed: Counter[str] = Counter()
    benchmark_order: list[str] = []
    summary_stream = sys.stdout if args.out else sys.stderr

    def run_slots(work_dir: Path) -> int:
        nonlocal hard_failures
        for repeat in range(1, args.repeats + 1):
            for slot in slots:
                benchmark = str(slot["benchmark"])
                count = int(slot["count"])
                selection = str(slot["selection"])
                if benchmark not in benchmark_order:
                    benchmark_order.append(benchmark)
                adapter = get_adapter(benchmark)
                try:
                    tasks = adapter.iter_tasks(count, selection, dry_run=args.dry_run)
                except NotImplementedError as exc:
                    hard_failures += count
                    print(real_mode_error(benchmark, adapter.real_infra, exc), file=summary_stream)
                    return 1
                except Exception as exc:  # pragma: no cover - exercised by CLI failure paths.
                    hard_failures += count
                    print(f"ERROR {benchmark} repeat={repeat}: {exc}", file=summary_stream)
                    continue

                for task in tasks:
                    task_id = str(task.get("id"))
                    try:
                        result = adapter.run_task(
                            task,
                            args.plugin_ref,
                            dry_run=args.dry_run,
                            repo_root=ROOT,
                            work_dir=work_dir,
                        )
                    except NotImplementedError as exc:
                        hard_failures += 1
                        print(real_mode_error(benchmark, adapter.real_infra, exc), file=summary_stream)
                        return 1
                    except Exception as exc:  # pragma: no cover - exercised by CLI failure paths.
                        hard_failures += 1
                        print(f"ERROR {benchmark}/{task_id} repeat={repeat}: {exc}", file=summary_stream)
                        continue

                    results.append(result)
                    per_benchmark_total[benchmark] += 1
                    if result.get("passed") is True:
                        per_benchmark_passed[benchmark] += 1
                    status = "PASS" if result.get("passed") is True else "FAIL"
                    print(
                        f"{status} {benchmark}/{result.get('case_id')} repeat={repeat} "
                        f"selection={selection} "
                        f"report_score={float(result.get('report_score', 0.0)):.2f} "
                        f"gate_passed={result.get('gate_passed')}",
                        file=summary_stream,
                    )
        return 0

    if args.dry_run:
        exit_code = run_slots(TIER_DRY_RUN_WORK_DIR)
    else:
        with tempfile.TemporaryDirectory(prefix="codex-orch-tier-") as temp_root:
            exit_code = run_slots(Path(temp_root))

    if args.out:
        write_jsonl(Path(args.out), results)
    else:
        for result in results:
            print(json.dumps(result, sort_keys=True))

    total_passed = sum(per_benchmark_passed.values())
    for benchmark in benchmark_order:
        print(
            f"Summary {benchmark}: {per_benchmark_passed[benchmark]}/{per_benchmark_total[benchmark]} "
            f"external passed",
            file=summary_stream,
        )
    print(
        f"Summary total: {total_passed}/{len(results)} external passed, "
        f"hard_failures={hard_failures}, expected_runs={expected_runs}",
        file=summary_stream,
    )
    return exit_code or (1 if hard_failures else 0)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.tier:
        return run_tier(args)
    cases = discover_cases(args.suite)
    if not cases:
        print(f"No benchmark cases found for suite {args.suite}", file=sys.stderr)
        return 1
    if args.suite == "local-mini":
        return run_local_mini_suite(args, cases)
    return run_replay_suite(args, cases)


if __name__ == "__main__":
    raise SystemExit(main())
