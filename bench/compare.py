from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from codex_orch import validate_benchmark_result  # noqa: E402


def load_result_set(path: Path) -> list[dict[str, object]]:
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        return []
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        records = [json.loads(line) for line in text.splitlines() if line.strip()]
    else:
        records = payload if isinstance(payload, list) else [payload]

    result: list[dict[str, object]] = []
    for record in records:
        if not isinstance(record, dict):
            raise ValueError(f"{path} contains a non-object benchmark record")
        validate_benchmark_result(record)
        result.append(record)
    return result


def mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def pass_rate(records: list[dict[str, object]]) -> float:
    if not records:
        return 0.0
    return sum(1 for record in records if record.get("passed") is True) / len(records)


def false_acceptance_count(records: list[dict[str, object]]) -> int:
    return sum(
        1
        for record in records
        if record.get("gate_passed") is True and record.get("passed") is False
    )


def mean_report_score(records: list[dict[str, object]]) -> float:
    return mean([float(record["report_score"]) for record in records])


def mean_wall_seconds(records: list[dict[str, object]]) -> float:
    values = [float(record["wall_seconds"]) for record in records if record.get("wall_seconds") is not None]
    return mean(values)


def signed(value: float, places: int = 4) -> str:
    return f"{value:+.{places}f}"


def signed_pp(value: float) -> str:
    return f"{value * 100:+.2f} pp"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Compare benchmark-result JSON or JSONL files.")
    parser.add_argument("--baseline", required=True, type=Path)
    parser.add_argument("--candidate", required=True, type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    baseline = load_result_set(args.baseline)
    candidate = load_result_set(args.candidate)

    baseline_pass = pass_rate(baseline)
    candidate_pass = pass_rate(candidate)
    baseline_false_accept = false_acceptance_count(baseline)
    candidate_false_accept = false_acceptance_count(candidate)
    baseline_score = mean_report_score(baseline)
    candidate_score = mean_report_score(candidate)
    baseline_wall = mean_wall_seconds(baseline)
    candidate_wall = mean_wall_seconds(candidate)

    print("Benchmark comparison")
    print(f"cases: baseline={len(baseline)} candidate={len(candidate)} delta={len(candidate) - len(baseline):+d}")
    print(
        "external pass rate: "
        f"baseline={baseline_pass * 100:.2f}% "
        f"candidate={candidate_pass * 100:.2f}% "
        f"delta={signed_pp(candidate_pass - baseline_pass)}"
    )
    print(
        "false-acceptance count: "
        f"baseline={baseline_false_accept} "
        f"candidate={candidate_false_accept} "
        f"delta={candidate_false_accept - baseline_false_accept:+d}"
    )
    print(
        "mean report_score: "
        f"baseline={baseline_score:.4f} "
        f"candidate={candidate_score:.4f} "
        f"delta={signed(candidate_score - baseline_score)}"
    )
    print(
        "mean wall_seconds: "
        f"baseline={baseline_wall:.4f} "
        f"candidate={candidate_wall:.4f} "
        f"delta={signed(candidate_wall - baseline_wall)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
