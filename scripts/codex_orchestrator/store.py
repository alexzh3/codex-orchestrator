from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path


PROTOCOL_VERSION = "1.0"
SCHEMA_VERSION = "1.0"
RUN_SUBDIRS = ("prompts", "logs", "artifacts")
UNSET = object()


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def print_json(payload: object) -> None:
    print(json.dumps(payload, indent=2, sort_keys=True))


def run_id_type(value: str) -> str:
    if not value or value in {".", ".."} or "/" in value or "\\" in value:
        raise argparse.ArgumentTypeError("run id must be a single path segment")
    return value


def name_type(value: str) -> str:
    if not value or value in {".", ".."} or "/" in value or "\\" in value:
        raise argparse.ArgumentTypeError("name must be a single path segment")
    return value


def repo_root(repo: str) -> Path:
    return Path(repo).expanduser().resolve()


def plugin_root() -> Path:
    return Path(__file__).resolve().parents[2]


def run_dir(repo: str, run_id: str) -> Path:
    return repo_root(repo) / ".codex-orchestrator" / "runs" / run_id


def state_path(directory: Path) -> Path:
    return directory / "state.json"


def ledger_path(directory: Path) -> Path:
    return directory / "ledger.jsonl"


def report_path(directory: Path) -> Path:
    return directory / "report.md"


def benchmark_path(directory: Path) -> Path:
    return directory / "benchmark.json"


def run_subdir(directory: Path, name: str) -> Path:
    return directory / name


def atomic_write_text(path: Path, text: str) -> None:
    tmp_path = path.with_name(f".{path.name}.tmp")
    tmp_path.write_text(text, encoding="utf-8")
    os.replace(tmp_path, path)


def write_text(path: Path, text: str, *, force: bool = False) -> bool:
    if path.exists() and not force:
        return False
    atomic_write_text(path, text)
    return True


def write_json(path: Path, payload: object, *, force: bool = False) -> bool:
    return write_text(path, json.dumps(payload, indent=2, sort_keys=True) + "\n", force=force)


def load_json(path: Path) -> dict[str, object]:
    if not path.exists():
        raise SystemExit(f"ERROR: missing run state: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SystemExit(f"ERROR: invalid JSON in {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise SystemExit(f"ERROR: run state must be a JSON object: {path}")
    return payload


def read_jsonl(path: Path) -> list[dict[str, object]]:
    records, _diagnostics = read_jsonl_with_warnings(path)
    return records


def read_jsonl_with_warnings(path: Path) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    records: list[dict[str, object]] = []
    diagnostics: list[dict[str, object]] = []
    if not path.exists():
        return records, diagnostics
    for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError as exc:
            diagnostics.append({"line_no": line_no, "error": str(exc)})
            continue
        if isinstance(record, dict):
            records.append(record)
    return records, diagnostics


def encode_jsonl_record(record: dict[str, object]) -> str:
    return json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n"


def append_jsonl(path: Path, record: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = encode_jsonl_record(record).encode("utf-8")
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
    try:
        written = os.write(fd, encoded)
        if written != len(encoded):
            raise OSError(f"short write to {path}: {written} of {len(encoded)} bytes")
        os.fsync(fd)
    finally:
        os.close(fd)
