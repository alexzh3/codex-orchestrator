from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "codex_orch_parse.py"
FIXTURES = ROOT / "tests" / "fixtures"


def run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        check=False,
        text=True,
        capture_output=True,
        cwd=ROOT,
    )


def run_cli_with_env(*args: str, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        check=False,
        text=True,
        capture_output=True,
        cwd=ROOT,
        env={**os.environ, **env},
    )


def test_exec_stream_completed_status():
    result = run_cli(
        "state",
        "exec-complete-001",
        "--source",
        "exec",
        "--file",
        str(FIXTURES / "exec_stream.jsonl"),
        "--json",
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["status"] == "complete"
    assert payload["compatibility"]["parse_confidence"] == "high"
    assert payload["compatibility"]["unknown_event_types"] == []


def test_rollout_idle_status():
    result = run_cli(
        "state",
        "ide-idle-001",
        "--source",
        "ide",
        "--file",
        str(FIXTURES / "rollout.jsonl"),
        "--json",
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["status"] == "idle"
    assert payload["compatibility"]["parse_confidence"] == "high"


def test_failed_turn_detected():
    result = run_cli(
        "state",
        "exec-failed-001",
        "--source",
        "exec",
        "--file",
        str(FIXTURES / "exec_failed_stream.jsonl"),
        "--json",
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["status"] == "failed"


def test_failed_rollout_signature_detected():
    result = run_cli(
        "state",
        "ide-failed-001",
        "--source",
        "ide",
        "--file",
        str(FIXTURES / "rollout_failed.jsonl"),
        "--json",
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["status"] == "failed"


def test_unknown_format_exits_nonzero_and_low_confidence():
    result = run_cli(
        "state",
        "unknown-001",
        "--source",
        "ide",
        "--file",
        str(FIXTURES / "unknown_format.jsonl"),
        "--json",
    )
    assert result.returncode != 0
    payload = json.loads(result.stdout)
    assert payload["compatibility"]["parse_confidence"] == "low"
    assert "Do not infer session status" in result.stderr


def test_tail_since_offset_emits_json_events():
    result = run_cli(
        "tail",
        "exec-complete-001",
        "--since-offset",
        "0",
        "--source",
        "exec",
        "--file",
        str(FIXTURES / "exec_stream.jsonl"),
        "--json",
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["next_offset"] > payload["offset"]
    assert payload["events"][0]["type"] == "thread.started"


def test_find_accepts_common_parser_flags():
    result = run_cli(
        "find",
        "exec-complete-001",
        "--source",
        "exec",
        "--file",
        str(FIXTURES / "exec_stream.jsonl"),
        "--dump-event-types",
        "--json",
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["source"] == "exec"
    assert payload["event_types"]["turn.completed"] == 1


def test_state_without_event_file_still_emits_status_json(tmp_path):
    result = run_cli_with_env(
        "state",
        "missing-thread",
        "--source",
        "exec",
        "--json",
        env={"HOME": str(tmp_path)},
    )
    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["status"] == "idle"
    assert payload["path"] is None


def test_ide_reader_uses_seek_tail_pattern():
    source = SCRIPT.read_text(encoding="utf-8")
    assert "seek(max(0, size - TAIL_LIMIT_BYTES))" in source
    assert ".readlines(" not in source
    assert ".read()" not in source
