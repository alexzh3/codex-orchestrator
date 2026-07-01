from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

from .events import validate_ledger_event
from .ledger import ledger_warning_messages
from .store import (
    PROTOCOL_VERSION,
    SCHEMA_VERSION,
    atomic_write_text,
    encode_jsonl_record,
    load_json,
    plugin_root,
    utc_now,
    write_json,
)


def run_git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True)


def default_branch(name: str) -> str:
    if name.startswith("codex-") and len(name) > len("codex-"):
        return f"codex/{name[len('codex-'):]}"
    return f"codex/{name}"


def find_active_state(repo: Path) -> Path:
    runs_dir = repo / ".codex-orchestrator" / "runs"
    candidates: list[Path] = []
    if runs_dir.exists():
        for path in runs_dir.glob("*/state.json"):
            try:
                state = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if isinstance(state, dict) and state.get("status") == "active":
                candidates.append(path)
    if not candidates:
        raise SystemExit("ERROR: no active run state found under .codex-orchestrator/runs")
    return max(candidates, key=lambda path: path.stat().st_mtime)


def upsert_session(
    path: Path,
    *,
    name: str,
    thread_id: str,
    mode: str,
    branch: str,
    worktree: Path,
) -> None:
    state = load_json(path)
    sessions = state.setdefault("sessions", [])
    if not isinstance(sessions, list):
        raise SystemExit(f"ERROR: sessions must be a list in {path}")
    session = {
        "name": name,
        "thread_id": thread_id,
        "mode": mode,
        "rollout_path": None,
        "branch": branch,
        "worktree": str(worktree),
        "status": "idle",
        "last_seen_at": utc_now(),
    }
    for index, existing in enumerate(sessions):
        if isinstance(existing, dict) and existing.get("name") == name:
            sessions[index] = {**existing, **session}
            break
    else:
        sessions.append(session)
    write_json(path, state, force=True)


def collect_warnings(
    state: dict[str, object],
    ledger_diagnostics: list[dict[str, object]] | None = None,
) -> list[str]:
    warnings: list[str] = []
    sessions = state.get("sessions")
    if isinstance(sessions, list):
        for session in sessions:
            if not isinstance(session, dict):
                continue
            name = session.get("name", "<unnamed>")
            if session.get("status") == "unknown":
                warnings.append(f"Session {name} has unknown status.")
            if session.get("parse_confidence") == "low":
                warnings.append(f"Session {name} has low parser confidence.")
    if ledger_diagnostics:
        warnings.extend(ledger_warning_messages(ledger_diagnostics))
    return warnings


def recommended_next_action(
    state: dict[str, object],
    verification: dict[str, object] | None,
    warnings: list[str] | None = None,
) -> str:
    active_warnings = warnings if warnings is not None else collect_warnings(state)
    if active_warnings:
        return "Inspect parser warnings or raw logs before trusting session status."
    if verification is None:
        return "Review the diff and record verification evidence."
    if state.get("status") not in {"complete", "accepted", "rejected"}:
        return "Finish review and update the run status or final report."
    return "No further action recorded."


def detect_git_sha(repo: Path) -> str | None:
    try:
        result = subprocess.run(
            ["git", "-C", str(repo), "rev-parse", "HEAD"],
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
    except OSError:
        return None
    if result.returncode != 0:
        return None
    sha = result.stdout.strip()
    return sha or None


def detect_plugin_version(root: Path) -> str | None:
    plugin_json = root / ".claude-plugin" / "plugin.json"
    if not plugin_json.exists():
        return None
    try:
        payload = json.loads(plugin_json.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    version = payload.get("version")
    return version if isinstance(version, str) and version else None


def detect_command_version(command: str) -> str | None:
    if shutil.which(command) is None:
        return None
    try:
        result = subprocess.run(
            [command, "--version"],
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    output = (result.stdout or result.stderr).strip()
    return output.splitlines()[0] if output else None


def default_run_config() -> dict[str, object]:
    return {
        "session_reuse_policy": None,
        "require_final_codex_review": None,
        "require_file_claims": None,
    }


def build_run_meta(
    *,
    repo: Path,
    run_id: str,
    plugin_ref: str | None = None,
    benchmark_suite: str | None = None,
    benchmark_case_id: str | None = None,
) -> dict[str, object]:
    repo_commit = detect_git_sha(repo)
    plugin_checkout = plugin_root()
    record: dict[str, object] = {
        "type": "run_meta",
        "recorded_at": utc_now(),
        "run_id": run_id,
        "plugin_version": detect_plugin_version(plugin_checkout),
        "plugin_git_sha": plugin_ref or detect_git_sha(plugin_checkout),
        "protocol_version": PROTOCOL_VERSION,
        "schema_version": SCHEMA_VERSION,
        "claude_code_version": None,
        "codex_cli_version": detect_command_version("codex"),
        "repo_commit": repo_commit,
        "benchmark_suite": benchmark_suite,
        "benchmark_case_id": benchmark_case_id,
        "config": default_run_config(),
    }
    validate_ledger_event(record)
    return record


def upsert_run_meta(path: Path, run_meta: dict[str, object]) -> dict[str, object]:
    path.parent.mkdir(parents=True, exist_ok=True)
    existing_lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    output_lines: list[str] = []
    replaced = False
    removed_duplicates = 0
    encoded = encode_jsonl_record(run_meta).rstrip("\n")
    for line in existing_lines:
        if not line.strip():
            output_lines.append(line)
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            output_lines.append(line)
            continue
        if isinstance(record, dict) and record.get("type") == "run_meta":
            if not replaced:
                output_lines.append(encoded)
                replaced = True
            else:
                removed_duplicates += 1
            continue
        output_lines.append(line)
    if not replaced:
        output_lines.append(encoded)
    atomic_write_text(path, "\n".join(output_lines) + "\n")
    return {
        "action": "updated" if replaced else "created",
        "removed_duplicates": removed_duplicates,
    }
