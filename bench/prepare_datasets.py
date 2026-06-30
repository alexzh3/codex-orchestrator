from __future__ import annotations

# RExBench privacy: gated data is licensed to prevent leakage. Do not commit,
# publish, or otherwise make public RExBench data, instructions, or agent outputs.

import argparse
import json
import os
from pathlib import Path
import tomllib
import urllib.parse
import urllib.request
import zipfile


ROOT = Path(__file__).resolve().parents[1]

BENCHMARKS = ("swebench_verified_mini", "tblite", "rexbench")
DEFAULT_SWEBENCH_LIMIT = 50

SWEBENCH_ROWS_ENDPOINT = "https://datasets-server.huggingface.co/rows"
SWEBENCH_DATASET = "princeton-nlp/SWE-bench_Verified"
SWEBENCH_SPLIT = "test"
SWEBENCH_PAGE_LENGTH = 100
SWEBENCH_GRADER_PLACEHOLDER = (
    "python3 -c \"raise SystemExit('SWE-bench Docker harness required "
    "(issues #2/#18)')\""
)

TBLITE_TREE_URL = "https://huggingface.co/api/datasets/open-thoughts/OpenThoughts-TBLite/tree/main?recursive=false"
TBLITE_RESOLVE_BASE = "https://huggingface.co/datasets/open-thoughts/OpenThoughts-TBLite/resolve/main"
TBLITE_NON_TASK_DIRS = {"assets"}
TBLITE_GRADER_PLACEHOLDER = (
    "python3 -c \"raise SystemExit('Harbor + tests/test.sh runner required "
    "for OpenThoughts-TBLite (issues #3/#18)')\""
)

REXBENCH_RESOLVE_BASE = "https://huggingface.co/datasets/tin-lab/RExBench/resolve/main"
REXBENCH_GRADER_PLACEHOLDER = (
    "python3 -c \"raise SystemExit('RExBench executor required "
    "(github.com/tinlaboratory/rexbench, issues #10/#18)')\""
)

SWE_DIFFICULTY_SCORES = {
    ">4 hours": 5.0,
    "1-4 hours": 4.0,
    "15 min - 1 hour": 3.0,
    "<15 min fix": 1.0,
}

TBLITE_DIFFICULTY_SCORES = {
    "expert": 5.0,
    "hardest": 5.0,
    "hard": 4.0,
    "medium": 3.0,
    "easy": 1.0,
}


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Fetch external benchmark datasets and write local adapter descriptors."
    )
    parser.add_argument(
        "--benchmark",
        choices=("all", *BENCHMARKS),
        default="all",
        help="Benchmark dataset to prepare.",
    )
    parser.add_argument(
        "--limit",
        type=positive_int,
        help="Maximum tasks to write per benchmark after hardness ranking.",
    )
    parser.add_argument(
        "--out-root",
        default="bench/datasets",
        help="Directory where benchmark descriptor directories are written.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the fetch/write plan without network or file writes.",
    )
    return parser.parse_args(argv)


def positive_int(value: str) -> int:
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("value must be at least 1")
    return parsed


def read_hf_token(repo_root: Path = ROOT) -> str | None:
    token = os.environ.get("HF_TOKEN")
    if token:
        return token

    env_path = repo_root / ".env"
    if not env_path.is_file():
        return None
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        if key.strip() != "HF_TOKEN":
            continue
        value = value.strip().strip("'\"")
        return value or None
    return None


def fetch_json(url: str, *, token: str | None = None) -> object:
    return json.loads(fetch_text(url, token=token))


def fetch_text(url: str, *, token: str | None = None) -> str:
    return fetch_bytes(url, token=token).decode("utf-8")


def fetch_bytes(url: str, *, token: str | None = None) -> bytes:
    headers = {"User-Agent": "codex-orchestrator-dataset-preparer"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(request, timeout=120) as response:
        return response.read()


def download_file(url: str, destination: Path, *, token: str | None = None) -> None:
    destination.write_bytes(fetch_bytes(url, token=token))


def hf_resolve_url(base: str, relative_path: str) -> str:
    return f"{base}/{urllib.parse.quote(relative_path, safe='/')}"


def write_jsonl(path: Path, records: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(jsonl_text(records), encoding="utf-8")


def jsonl_text(records: list[dict[str, object]]) -> str:
    return "".join(json.dumps(record, sort_keys=True) + "\n" for record in records)


def resolve_out_root(raw_path: str) -> Path:
    path = Path(raw_path).expanduser()
    if path.is_absolute():
        return path
    return ROOT / path


def unwrap_hf_row(value: object) -> dict[str, object]:
    if isinstance(value, dict) and isinstance(value.get("row"), dict):
        return value["row"]
    if isinstance(value, dict):
        return value
    raise ValueError("dataset row must be a JSON object")


def fetch_swebench_rows(*, token: str | None = None) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    offset = 0
    while True:
        query = urllib.parse.urlencode(
            {
                "dataset": SWEBENCH_DATASET,
                "config": "default",
                "split": SWEBENCH_SPLIT,
                "offset": offset,
                "length": SWEBENCH_PAGE_LENGTH,
            }
        )
        payload = fetch_json(f"{SWEBENCH_ROWS_ENDPOINT}?{query}", token=token)
        if not isinstance(payload, dict):
            raise ValueError("SWE-bench datasets-server response must be a JSON object")
        page = payload.get("rows")
        if not isinstance(page, list) or not page:
            break
        rows.extend(unwrap_hf_row(item) for item in page)
        offset += len(page)
        total = payload.get("num_rows_total")
        if isinstance(total, int) and offset >= total:
            break
        if len(page) < SWEBENCH_PAGE_LENGTH:
            break
    return rows


def swebench_difficulty_score(difficulty: object) -> float | None:
    if not isinstance(difficulty, str):
        return None
    return SWE_DIFFICULTY_SCORES.get(difficulty.strip())


def convert_swebench_rows(rows: list[dict[str, object]], *, limit: int | None = None) -> list[dict[str, object]]:
    tasks: list[dict[str, object]] = []
    for raw_row in rows:
        row = unwrap_hf_row(raw_row)
        difficulty_score = swebench_difficulty_score(row.get("difficulty"))
        if difficulty_score is None or difficulty_score < 4.0:
            continue
        instance_id = require_string(row, "instance_id")
        tasks.append(
            {
                "instance_id": instance_id,
                "repo": require_string(row, "repo"),
                "base_commit": require_string(row, "base_commit"),
                "environment_setup_commit": row.get("environment_setup_commit"),
                "problem_statement": require_string(row, "problem_statement"),
                "FAIL_TO_PASS": row.get("FAIL_TO_PASS"),
                "PASS_TO_PASS": row.get("PASS_TO_PASS"),
                "difficulty": row.get("difficulty"),
                "difficulty_score": difficulty_score,
                "files_allowed": ["*", "**/*"],
                "grader_command": SWEBENCH_GRADER_PLACEHOLDER,
            }
        )

    tasks.sort(key=lambda task: (-float(task["difficulty_score"]), str(task["instance_id"])))
    return tasks[:limit] if limit is not None else tasks


def swebench_repo_lines(tasks: list[dict[str, object]]) -> list[str]:
    pairs = {
        f"{task['repo']}@{task['base_commit']}"
        for task in tasks
        if isinstance(task.get("repo"), str) and isinstance(task.get("base_commit"), str)
    }
    return sorted(pairs)


def fetch_tblite_task_dirs(*, token: str | None = None) -> list[str]:
    payload = fetch_json(TBLITE_TREE_URL, token=token)
    items: list[object]
    if isinstance(payload, list):
        items = payload
    elif isinstance(payload, dict) and isinstance(payload.get("siblings"), list):
        items = payload["siblings"]
    else:
        raise ValueError("OpenThoughts-TBLite tree response must be a JSON array")

    dirs: list[str] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        path = item.get("path") or item.get("rfilename")
        kind = item.get("type")
        if kind != "directory" or not isinstance(path, str) or not path:
            continue
        if path in TBLITE_NON_TASK_DIRS or path.startswith("."):
            continue
        dirs.append(path)
    return sorted(dirs)


def fetch_tblite_raw_tasks(task_dirs: list[str], *, token: str | None = None) -> list[tuple[str, str, str]]:
    raw_tasks: list[tuple[str, str, str]] = []
    for task_dir in task_dirs:
        task_toml = fetch_text(hf_resolve_url(TBLITE_RESOLVE_BASE, f"{task_dir}/task.toml"), token=token)
        instruction = fetch_text(
            hf_resolve_url(TBLITE_RESOLVE_BASE, f"{task_dir}/instruction.md"),
            token=token,
        )
        raw_tasks.append((task_dir, task_toml, instruction))
    return raw_tasks


def tblite_difficulty_score(difficulty: object) -> float | None:
    if not isinstance(difficulty, str):
        return None
    normalized = difficulty.strip().lower().replace("_", "-").replace(" ", "-")
    for key, score in TBLITE_DIFFICULTY_SCORES.items():
        if key in normalized:
            return score
    return None


def convert_tblite_task(task_id: str, task_toml: str, instruction: str) -> dict[str, object]:
    payload = tomllib.loads(task_toml)
    metadata = mapping(payload.get("metadata"))
    verifier = mapping(payload.get("verifier"))
    agent = mapping(payload.get("agent"))
    environment = mapping(payload.get("environment"))

    difficulty = metadata.get("difficulty")
    expert_time = number_or_none(metadata.get("expert_time_estimate_min"))
    timeout_seconds = first_int(
        verifier.get("timeout_sec"),
        verifier.get("timeout_seconds"),
        agent.get("timeout_sec"),
        agent.get("timeout_seconds"),
        environment.get("timeout_sec"),
        environment.get("timeout_seconds"),
    )

    task: dict[str, object] = {
        "id": task_id,
        "prompt": instruction,
        "difficulty": difficulty,
        "difficulty_score": tblite_difficulty_score(difficulty),
        "expert_time_estimate_min": expert_time,
        "category": metadata.get("category"),
        "tags": metadata.get("tags"),
        "timeout_seconds": timeout_seconds,
        "files_allowed": ["*", "**/*"],
        "grader_command": TBLITE_GRADER_PLACEHOLDER,
        "tblite_task_dir": task_id,
    }
    return task


def convert_tblite_tasks(raw_tasks: list[tuple[str, str, str]], *, limit: int | None = None) -> list[dict[str, object]]:
    tasks = [convert_tblite_task(task_id, task_toml, instruction) for task_id, task_toml, instruction in raw_tasks]
    tasks.sort(key=tblite_sort_key)
    return tasks[:limit] if limit is not None else tasks


def tblite_sort_key(task: dict[str, object]) -> tuple[int, float, int, float, str]:
    score = number_or_none(task.get("difficulty_score"))
    expert_time = number_or_none(task.get("expert_time_estimate_min"))
    return (
        1 if score is None else 0,
        -(score or 0.0),
        1 if expert_time is None else 0,
        -(expert_time or 0.0),
        str(task.get("id", "")),
    )


def download_and_extract_rexbench(out_dir: Path, *, token: str | None = None) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    zip_path = out_dir / "dataset.zip"
    download_file(hf_resolve_url(REXBENCH_RESOLVE_BASE, "dataset.zip"), zip_path, token=token)
    safe_extract_zip(zip_path, out_dir)
    return find_rexbench_task_dirs(out_dir)


def safe_extract_zip(zip_path: Path, destination: Path) -> None:
    destination = destination.resolve()
    with zipfile.ZipFile(zip_path) as archive:
        for info in archive.infolist():
            target = (destination / info.filename).resolve()
            if destination != target and destination not in target.parents:
                raise ValueError(f"refusing to extract path outside destination: {info.filename}")
        archive.extractall(destination)


def find_rexbench_task_dirs(out_dir: Path) -> list[Path]:
    dirs = candidate_rexbench_task_dirs(out_dir)
    if len(dirs) == 1 and dirs[0].name in {"dataset", "tasks", "rexbench"}:
        nested = candidate_rexbench_task_dirs(dirs[0])
        if nested:
            return nested
    return dirs


def candidate_rexbench_task_dirs(root: Path) -> list[Path]:
    skip = {"__MACOSX", "instructions"}
    return sorted(
        path
        for path in root.iterdir()
        if path.is_dir() and not path.name.startswith(".") and path.name not in skip
    )


def fetch_rexbench_instruction(task_id: str, *, token: str | None = None) -> str:
    return fetch_text(
        hf_resolve_url(REXBENCH_RESOLVE_BASE, f"instructions/{task_id}/instructions.md"),
        token=token,
    )


def load_rexbench_metadata(task_dir: Path) -> dict[str, object]:
    for name in ("metadata.json", "task.json", "config.json"):
        path = task_dir / name
        if path.is_file():
            payload = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(payload, dict):
                return payload
    return {}


def convert_rexbench_task(
    task_id: str,
    instructions: str,
    target_repo_path: str,
    metadata: dict[str, object] | None = None,
) -> dict[str, object]:
    metadata = metadata or {}
    task: dict[str, object] = {
        "id": task_id,
        "prompt": instructions,
        "target_repo_path": target_repo_path,
        "difficulty_score": difficulty_signal(metadata),
        "files_allowed": ["*", "**/*"],
        "grader_command": REXBENCH_GRADER_PLACEHOLDER,
    }
    success_rate = success_rate_signal(metadata)
    if success_rate is not None:
        task["success_rate"] = success_rate
    return task


def convert_rexbench_tasks(
    task_dirs: list[Path],
    out_dir: Path,
    *,
    token: str | None = None,
    limit: int | None = None,
) -> list[dict[str, object]]:
    tasks: list[dict[str, object]] = []
    for task_dir in task_dirs:
        task_id = task_dir.name
        instructions = fetch_rexbench_instruction(task_id, token=token)
        target_path = str(task_dir.relative_to(out_dir))
        tasks.append(convert_rexbench_task(task_id, instructions, target_path, load_rexbench_metadata(task_dir)))
    tasks.sort(key=rexbench_sort_key)
    return tasks[:limit] if limit is not None else tasks


def rexbench_sort_key(task: dict[str, object]) -> tuple[int, float, str]:
    score = number_or_none(task.get("difficulty_score"))
    return (1 if score is None else 0, -(score or 0.0), str(task.get("id", "")))


def difficulty_signal(metadata: dict[str, object]) -> float | None:
    for key in ("difficulty_score", "hardness_score", "score"):
        value = number_or_none(metadata.get(key))
        if value is not None:
            return value
    for key in ("difficulty", "difficulty_band", "hardness"):
        value = metadata.get(key)
        score = tblite_difficulty_score(value)
        if score is not None:
            return score
    return None


def success_rate_signal(metadata: dict[str, object]) -> float | None:
    for key in ("success_rate", "pass_rate", "solve_rate", "baseline_success_rate"):
        value = number_or_none(metadata.get(key))
        if value is not None:
            return value / 100.0 if value > 1.0 and value <= 100.0 else value
    return None


def require_string(payload: dict[str, object], field: str) -> str:
    value = payload.get(field)
    if not isinstance(value, str) or not value:
        raise ValueError(f"row is missing non-empty field {field}")
    return value


def mapping(value: object) -> dict[str, object]:
    return value if isinstance(value, dict) else {}


def number_or_none(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip())
        except ValueError:
            return None
    return None


def first_int(*values: object) -> int | None:
    for value in values:
        if isinstance(value, bool):
            continue
        if isinstance(value, int):
            return value
        if isinstance(value, float) and value.is_integer():
            return int(value)
    return None


def selected_benchmarks(name: str) -> tuple[str, ...]:
    return BENCHMARKS if name == "all" else (name,)


def prepare_swebench(out_root: Path, *, limit: int | None, dry_run: bool, token: str | None = None) -> None:
    out_dir = out_root / "swebench_verified_mini"
    descriptor = out_dir / "instances.jsonl"
    repos = out_dir / "repos.txt"
    effective_limit = limit if limit is not None else DEFAULT_SWEBENCH_LIMIT
    if dry_run:
        print(
            "SWE-bench Verified Mini: would fetch "
            f"{SWEBENCH_DATASET}/{SWEBENCH_SPLIT} rows from {SWEBENCH_ROWS_ENDPOINT}, "
            "keep 1hr+ difficulty bands, rank by difficulty_score desc then instance_id, "
            f"and write up to {effective_limit} instances to {display_path(descriptor)} "
            f"plus {display_path(repos)}."
        )
        return

    rows = fetch_swebench_rows(token=token)
    tasks = convert_swebench_rows(rows, limit=effective_limit)
    write_jsonl(descriptor, tasks)
    repos.write_text("\n".join(swebench_repo_lines(tasks)) + ("\n" if tasks else ""), encoding="utf-8")
    print(f"SWE-bench Verified Mini: wrote {len(tasks)} tasks to {display_path(descriptor)}")


def prepare_tblite(out_root: Path, *, limit: int | None, dry_run: bool, token: str | None = None) -> None:
    out_dir = out_root / "tblite"
    descriptor = out_dir / "tasks.jsonl"
    limit_text = str(limit) if limit is not None else "all ranked"
    if dry_run:
        print(
            "OpenThoughts-TBLite: would list task directories from Hugging Face, "
            "fetch task.toml and instruction.md per task, rank by difficulty_score desc, "
            "expert_time_estimate_min desc, then id, "
            f"and write {limit_text} tasks to {display_path(descriptor)}."
        )
        return

    task_dirs = fetch_tblite_task_dirs(token=token)
    raw_tasks = fetch_tblite_raw_tasks(task_dirs, token=token)
    tasks = convert_tblite_tasks(raw_tasks, limit=limit)
    write_jsonl(descriptor, tasks)
    print(f"OpenThoughts-TBLite: wrote {len(tasks)} tasks to {display_path(descriptor)}")


def prepare_rexbench(out_root: Path, *, limit: int | None, dry_run: bool, token: str | None = None) -> None:
    out_dir = out_root / "rexbench"
    descriptor = out_dir / "tasks.jsonl"
    limit_text = str(limit) if limit is not None else "all"
    if dry_run:
        print(
            "RExBench: would download gated dataset.zip and instructions from Hugging Face "
            "using HF_TOKEN when configured, unzip under the gitignored dataset directory, "
            "rank by any bundled difficulty signal if present, "
            f"and write {limit_text} tasks to {display_path(descriptor)}. "
            "Do not publish RExBench data or agent outputs."
        )
        return

    task_dirs = download_and_extract_rexbench(out_dir, token=token)
    tasks = convert_rexbench_tasks(task_dirs, out_dir, token=token, limit=limit)
    write_jsonl(descriptor, tasks)
    print(f"RExBench: wrote {len(tasks)} tasks to {display_path(descriptor)}")


def display_path(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    out_root = resolve_out_root(args.out_root)
    token = None if args.dry_run else read_hf_token(ROOT)
    preparers = {
        "swebench_verified_mini": prepare_swebench,
        "tblite": prepare_tblite,
        "rexbench": prepare_rexbench,
    }
    for benchmark in selected_benchmarks(args.benchmark):
        preparers[benchmark](out_root, limit=args.limit, dry_run=args.dry_run, token=token)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
