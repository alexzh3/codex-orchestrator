from __future__ import annotations

import json
from pathlib import Path

from .store import (
    RUN_SUBDIRS,
    ledger_path,
    read_jsonl,
    report_path,
    run_subdir,
    state_path,
    utc_now,
    write_json,
    write_text,
)


def initial_state(repo: Path, run_id: str) -> dict[str, object]:
    return {
        "run_id": run_id,
        "repo": str(repo),
        "created_at": utc_now(),
        "status": "active",
        "sessions": [],
    }


def initial_report_text() -> str:
    return (
        "# Report\n\n"
        "## Summary\n\n"
        "## Reproducibility\n\n"
        "## Changes\n\n"
        "## Evidence\n\n"
        "## Consensus\n\n"
        "## Gate Result\n\n"
        "## Risks / Follow-ups\n\n"
    )


def ensure_run_scaffold(repo: Path, run_id: str, *, force: bool = False) -> tuple[Path, dict[str, bool]]:
    directory = repo / ".codex-orchestrator" / "runs" / run_id
    directory.mkdir(parents=True, exist_ok=True)
    created = {
        "state.json": write_json(state_path(directory), initial_state(repo, run_id), force=force),
        "ledger.jsonl": write_text(ledger_path(directory), "", force=force),
        "report.md": write_text(report_path(directory), initial_report_text(), force=force),
    }
    for name in RUN_SUBDIRS:
        subdir = run_subdir(directory, name)
        already_exists = subdir.exists()
        subdir.mkdir(parents=True, exist_ok=True)
        created[f"{name}/"] = not already_exists
    return directory, created


def ledger_records(directory: Path, record_type: str | None = None) -> list[dict[str, object]]:
    records = read_jsonl(ledger_path(directory))
    if record_type is None:
        return records
    return [record for record in records if record.get("type") == record_type]


def records_of_type(records: list[dict[str, object]], record_type: str) -> list[dict[str, object]]:
    return [record for record in records if record.get("type") == record_type]


def latest_verification(directory: Path) -> dict[str, object] | None:
    records = ledger_records(directory, "verification")
    return records[-1] if records else None


def latest_verification_from_records(records: list[dict[str, object]]) -> dict[str, object] | None:
    verifications = records_of_type(records, "verification")
    return verifications[-1] if verifications else None


def ledger_warning_messages(diagnostics: list[dict[str, object]]) -> list[str]:
    if not diagnostics:
        return []
    messages = [f"Ledger contains {len(diagnostics)} malformed JSON line(s)."]
    for diagnostic in diagnostics:
        line_no = diagnostic.get("line_no")
        error = diagnostic.get("error")
        messages.append(f"ledger.jsonl line {line_no}: {error}")
    return messages


def load_event(raw: str) -> dict[str, object]:
    try:
        event = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"ERROR: event is not valid JSON: {exc}") from exc
    if not isinstance(event, dict):
        raise SystemExit("ERROR: event must be a JSON object")
    return event
