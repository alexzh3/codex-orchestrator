from __future__ import annotations

import argparse
from collections import Counter
import json
import re
import sys
import tempfile
from pathlib import Path

from bench.runners.run_claude import empty_token_usage
from bench.runners.run_claude import load_case as load_local_mini_case
from bench.runners.run_claude import run_case as run_local_mini_case
from bench.runners.run_replay import run_case as run_replay_case
from bench.adapters import get_adapter


ROOT = Path(__file__).resolve().parents[1]
CASE_ROOT = ROOT / "bench" / "cases"
TIERS_PATH = ROOT / "bench" / "tiers.json"
DRY_RUN_WORK_DIR = Path("/tmp/codex-orch-local-mini-dry-run")
TIER_DRY_RUN_WORK_DIR = Path("/tmp/codex-orch-tier-dry-run")
TOKEN_TOTAL_FIELDS = ("input_tokens", "output_tokens", "total_tokens")
TIER_STATUS_VALUES = {"runnable", "adapter_pending", "external_grading_only"}
TIER_SLOT_KEYS = {"benchmark", "status", "issue", "pin", "tasks"}
TIER_FALLBACK_CHOICES = ("tiny", "frontier")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


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
    target.add_argument("--tier", choices=_tier_choices(), help="Head-to-head benchmark tier to run.")
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


def _token_usage_from_result(result: dict[str, object]) -> dict[str, object] | None:
    token_usage = result.get("token_usage")
    if isinstance(token_usage, dict):
        return token_usage
    external_score = result.get("external_score")
    if isinstance(external_score, dict):
        nested_score = external_score.get("run_claude_external_score")
        if isinstance(nested_score, dict):
            nested_usage = nested_score.get("token_usage")
            if isinstance(nested_usage, dict):
                return nested_usage
    return None


def _ensure_token_usage(result: dict[str, object]) -> None:
    token_usage = _token_usage_from_result(result)
    result["token_usage"] = dict(token_usage) if token_usage is not None else empty_token_usage()


def _token_summary(results: list[dict[str, object]]) -> dict[str, int | float]:
    totals: dict[str, int | float] = {
        "input_tokens": 0,
        "output_tokens": 0,
        "total_tokens": 0,
        "cost_usd": 0.0,
    }
    for result in results:
        token_usage = _token_usage_from_result(result)
        if not isinstance(token_usage, dict):
            continue
        for field in TOKEN_TOTAL_FIELDS:
            value = token_usage.get(field)
            if type(value) is int and value >= 0:
                totals[field] += value
        cost = token_usage.get("cost_usd")
        if isinstance(cost, bool):
            continue
        if isinstance(cost, (int, float)) and cost >= 0:
            totals["cost_usd"] += float(cost)
    return totals


def print_token_summary(results: list[dict[str, object]], stream: object) -> None:
    totals = _token_summary(results)
    print(
        f"Summary tokens: input={totals['input_tokens']} "
        f"output={totals['output_tokens']} total={totals['total_tokens']} "
        f"cost_usd={float(totals['cost_usd']):.6f}",
        file=stream,
    )


def _tier_choices(path: Path = TIERS_PATH) -> tuple[str, ...]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        tiers = payload.get("tiers") if isinstance(payload, dict) else None
        if not isinstance(tiers, dict):
            return TIER_FALLBACK_CHOICES
        choices = tuple(sorted(key for key in tiers if isinstance(key, str) and key))
        return choices or TIER_FALLBACK_CHOICES
    except Exception:
        return TIER_FALLBACK_CHOICES


def load_tier_slots(tier: str, path: Path = TIERS_PATH) -> list[dict[str, object]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must contain a JSON object")
    if payload.get("schema_version") != 2:
        raise ValueError(f"{path} must have schema_version 2")
    tiers = payload.get("tiers")
    if not isinstance(tiers, dict):
        raise ValueError(f"{path} is missing tiers")
    raw_slots = tiers.get(tier)
    if not isinstance(raw_slots, list):
        raise ValueError(f"{path} is missing tier {tier!r}")

    slots: list[dict[str, object]] = []
    seen_tier_pairs: set[tuple[str, str]] = set()
    for index, raw_slot in enumerate(raw_slots, start=1):
        if not isinstance(raw_slot, dict):
            raise ValueError(f"{tier} slot {index} must be an object")
        unknown_keys = set(raw_slot) - TIER_SLOT_KEYS
        if unknown_keys:
            keys = ", ".join(sorted(unknown_keys))
            raise ValueError(f"{tier} slot {index} has unknown keys: {keys}")
        benchmark = raw_slot.get("benchmark")
        status = raw_slot.get("status")
        issue = raw_slot.get("issue")
        pin = raw_slot.get("pin")
        raw_tasks = raw_slot.get("tasks")
        if not isinstance(benchmark, str) or not benchmark:
            raise ValueError(f"{tier} slot {index} is missing benchmark")
        if status not in TIER_STATUS_VALUES:
            raise ValueError(f"{tier} slot {index} status must be one of {sorted(TIER_STATUS_VALUES)}")
        if status != "runnable" and (not isinstance(issue, str) or not issue):
            raise ValueError(f"{tier} slot {index} status {status} requires a non-empty issue")
        if issue is not None and (not isinstance(issue, str) or not issue):
            raise ValueError(f"{tier} slot {index} issue must be a non-empty string when present")
        if not isinstance(pin, dict) or not pin:
            raise ValueError(f"{tier} slot {index} pin must be a non-empty object")
        if not isinstance(raw_tasks, list) or not raw_tasks:
            raise ValueError(f"{tier} slot {index} tasks must be a non-empty list")

        tasks: list[dict[str, object]] = []
        seen_slot_ids: set[str] = set()
        for task_index, raw_task in enumerate(raw_tasks, start=1):
            if not isinstance(raw_task, dict):
                raise ValueError(f"{tier} slot {index} task {task_index} must be an object")
            task_id = raw_task.get("id")
            reason = raw_task.get("reason")
            sha256 = raw_task.get("sha256")
            if not isinstance(task_id, str) or not task_id:
                raise ValueError(f"{tier} slot {index} task {task_index} is missing id")
            if not isinstance(reason, str) or not reason:
                raise ValueError(f"{tier} slot {index} task {task_index} is missing reason")
            if sha256 is not None and (not isinstance(sha256, str) or SHA256_RE.fullmatch(sha256) is None):
                raise ValueError(f"{tier} slot {index} task {task_index} sha256 must be null or 64-char lowercase hex")
            if task_id in seen_slot_ids:
                raise ValueError(f"{tier} slot {index} has duplicate task id {task_id!r}")
            pair = (benchmark, task_id)
            if pair in seen_tier_pairs:
                raise ValueError(f"{tier} has duplicate benchmark/id pair {benchmark}/{task_id}")
            seen_slot_ids.add(task_id)
            seen_tier_pairs.add(pair)
            tasks.append({"id": task_id, "reason": reason, "sha256": sha256})

        slots.append(
            {
                "benchmark": benchmark,
                "status": status,
                "issue": issue,
                "tasks": tasks,
                "count": len(tasks),
            }
        )
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

                _ensure_token_usage(result)
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
    print_token_summary(results, summary_stream)
    return 1 if hard_failures else 0


def real_mode_error(benchmark: str, infra: str, exc: NotImplementedError) -> str:
    return f"real {benchmark} runs require {infra}; use --dry-run or implement the adapter (issue #N): {exc}"


def gated_tier_message(benchmark: str, status: str, issue: object) -> str:
    issue_text = str(issue) if isinstance(issue, str) and issue else "untracked"
    if status == "adapter_pending":
        requirement = f"the {benchmark} adapter"
    elif status == "external_grading_only":
        requirement = f"the {benchmark} external grading workflow"
    else:
        requirement = f"{benchmark} real-run support"
    return (
        f"GATED {benchmark}: {status} - real runs require {requirement} "
        f"({issue_text}); tasks are frozen in bench/tiers.json"
    )


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
                status_value = str(slot["status"])
                if benchmark not in benchmark_order:
                    benchmark_order.append(benchmark)
                if not args.dry_run and status_value != "runnable":
                    hard_failures += count
                    print(gated_tier_message(benchmark, status_value, slot.get("issue")), file=summary_stream)
                    continue
                adapter = get_adapter(benchmark)
                try:
                    tasks = adapter.resolve_frozen_tasks(
                        slot["tasks"],  # type: ignore[arg-type]
                        dry_run=args.dry_run,
                    )
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

                    _ensure_token_usage(result)
                    results.append(result)
                    per_benchmark_total[benchmark] += 1
                    if result.get("passed") is True:
                        per_benchmark_passed[benchmark] += 1
                    status = "PASS" if result.get("passed") is True else "FAIL"
                    print(
                        f"{status} {benchmark}/{result.get('case_id')} repeat={repeat} "
                        "selection=frozen "
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
    print_token_summary(results, summary_stream)
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
