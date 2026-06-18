#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


ALLOWED_VERIFICATION_KINDS = (
    "git_diff",
    "test",
    "typecheck",
    "lint",
    "build",
    "benchmark",
    "screenshot",
    "artifact_check",
    "manual_review",
    "custom",
)

ALLOWED_VERIFICATION_RESULTS = (
    "passed",
    "failed",
    "skipped",
    "inconclusive",
    "needs_human_review",
)

CONSENSUS_PLACEHOLDER = "No consensus decisions recorded."
REVIEW_PLACEHOLDER = "No review notes recorded."
SUMMARY_PLACEHOLDER = "No authored summary recorded."
CHANGES_PLACEHOLDER = "No authored changes recorded."
EVIDENCE_PLACEHOLDER = "No evidence recorded."
RISKS_PLACEHOLDER = "No unresolved risks or follow-ups recorded."
REVIEW_KINDS = {"manual_review", "git_diff"}
RUN_SUBDIRS = ("prompts", "logs", "artifacts")
SUMMARY_OPEN_ITEM_LIMIT = 140
TASK_STATUS_ORDER = ("complete", "active", "pending", "blocked", "failed")
TASK_RISK_STATUSES = {"blocked", "failed"}
UNRESOLVED_VERIFICATION_RESULTS = {"failed", "inconclusive", "needs_human_review"}
UNRESOLVED_CONSENSUS_STATUSES = {"deferred", "rejected"}
VERIFICATION_KIND_LABELS = {
    "artifact_check": "Artifact check",
    "benchmark": "Benchmark",
    "build": "Build",
    "custom": "Custom check",
    "git_diff": "Git diff review",
    "lint": "Lint",
    "manual_review": "Manual / agent review",
    "screenshot": "Screenshot check",
    "test": "Test",
    "typecheck": "Typecheck",
}


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


def run_dir(repo: str, run_id: str) -> Path:
    return repo_root(repo) / ".codex-orchestrator" / "runs" / run_id


def state_path(directory: Path) -> Path:
    return directory / "state.json"


def ledger_path(directory: Path) -> Path:
    return directory / "ledger.jsonl"


def report_path(directory: Path) -> Path:
    return directory / "report.md"


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
    records: list[dict[str, object]] = []
    if not path.exists():
        return records
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(record, dict):
            records.append(record)
    return records


def append_jsonl(path: Path, record: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = (json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
    try:
        written = os.write(fd, encoded)
        if written != len(encoded):
            raise OSError(f"short write to {path}: {written} of {len(encoded)} bytes")
        os.fsync(fd)
    finally:
        os.close(fd)


def initial_state(repo: Path, run_id: str) -> dict[str, object]:
    return {
        "run_id": run_id,
        "repo": str(repo),
        "created_at": utc_now(),
        "status": "active",
        "sessions": [],
    }


def ledger_records(directory: Path, record_type: str | None = None) -> list[dict[str, object]]:
    records = read_jsonl(ledger_path(directory))
    if record_type is None:
        return records
    return [record for record in records if record.get("type") == record_type]


def latest_verification(directory: Path) -> dict[str, object] | None:
    records = ledger_records(directory, "verification")
    return records[-1] if records else None


def load_event(raw: str) -> dict[str, object]:
    try:
        event = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"ERROR: event is not valid JSON: {exc}") from exc
    if not isinstance(event, dict):
        raise SystemExit("ERROR: event must be a JSON object")
    return event


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


def collect_warnings(state: dict[str, object]) -> list[str]:
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
    return warnings


def recommended_next_action(state: dict[str, object], verification: dict[str, object] | None) -> str:
    if collect_warnings(state):
        return "Inspect parser warnings or raw logs before trusting session status."
    if verification is None:
        return "Review the diff and record verification evidence."
    if state.get("status") not in {"complete", "accepted", "rejected"}:
        return "Finish review and update the run status or final report."
    return "No further action recorded."


def command_init(args: argparse.Namespace) -> int:
    repo = repo_root(args.repo)
    if not repo.exists() or not repo.is_dir():
        raise SystemExit(f"ERROR: repo does not exist or is not a directory: {repo}")

    directory = run_dir(args.repo, args.run_id)
    directory.mkdir(parents=True, exist_ok=True)
    created = {
        "state.json": write_json(state_path(directory), initial_state(repo, args.run_id), force=args.force),
        "ledger.jsonl": write_text(ledger_path(directory), "", force=args.force),
        "report.md": write_text(
            report_path(directory),
            (
                "# Report\n\n"
                "## Summary\n\n"
                "## Changes\n\n"
                "## Evidence\n\n"
                "## Consensus\n\n"
                "## Risks / Follow-ups\n\n"
            ),
            force=args.force,
        ),
    }
    for name in RUN_SUBDIRS:
        subdir = run_subdir(directory, name)
        already_exists = subdir.exists()
        subdir.mkdir(parents=True, exist_ok=True)
        created[f"{name}/"] = not already_exists
    print_json({"ok": True, "run_id": args.run_id, "run_dir": str(directory), "created_or_replaced": created})
    return 0


def command_add_verification(args: argparse.Namespace) -> int:
    directory = run_dir(args.repo, args.run_id)
    load_json(state_path(directory))
    record: dict[str, object] = {
        "type": "verification",
        "recorded_at": utc_now(),
        "kind": args.kind,
        "result": args.result,
        "summary": args.summary,
    }
    if args.command:
        record["command"] = args.command
    if args.exit_code is not None:
        record["exit_code"] = args.exit_code
    if args.artifact:
        record["artifacts"] = args.artifact
    if args.notes:
        record["notes"] = args.notes
    append_jsonl(ledger_path(directory), record)
    print_json({"ok": True, "verification": record})
    return 0


def command_append_event(args: argparse.Namespace) -> int:
    directory = run_dir(args.repo, args.run_id)
    load_json(state_path(directory))
    raw_event = args.event_option if args.event_option is not None else args.event_json
    if raw_event is None:
        raw_event = sys.stdin.read()
    raw_event = raw_event.strip()
    if not raw_event:
        raise SystemExit("ERROR: no event JSON provided")
    event = load_event(raw_event)
    event.setdefault("type", "event")
    append_jsonl(ledger_path(directory), event)
    print_json({"ok": True, "ledger_path": str(ledger_path(directory)), "event": event})
    return 0


def command_status(args: argparse.Namespace) -> int:
    directory = run_dir(args.repo, args.run_id)
    state = load_json(state_path(directory))
    sessions = state.get("sessions") if isinstance(state.get("sessions"), list) else []
    verification = latest_verification(directory)
    warnings = collect_warnings(state)
    payload = {
        "run_id": state.get("run_id"),
        "status": state.get("status"),
        "repo": state.get("repo"),
        "session_count": len(sessions),
        "sessions": sessions[-5:],
        "latest_verification": verification,
        "warnings": warnings,
        "recommended_next_action": recommended_next_action(state, verification),
    }
    print_json(payload)
    return 0


def command_worktree(args: argparse.Namespace) -> int:
    repo = repo_root(args.repo)
    if not repo.exists() or not repo.is_dir():
        raise SystemExit(f"ERROR: repo does not exist or is not a directory: {repo}")
    branch = args.branch or default_branch(args.name)
    worktree = (
        Path(args.worktree).expanduser()
        if args.worktree
        else repo.parent / f"repo-{args.name}"
    ).resolve()
    state_file = state_path(run_dir(args.repo, args.run_id)) if args.run_id else find_active_state(repo)
    load_json(state_file)

    run_git(repo, "worktree", "add", str(worktree), "-b", branch, args.base)
    upsert_session(
        state_file,
        name=args.name,
        thread_id=args.thread_id or f"pending:{args.name}",
        mode=args.mode,
        branch=branch,
        worktree=worktree,
    )
    print_json({"ok": True, "branch": branch, "worktree": str(worktree), "state": str(state_file)})
    return 0


def report_section(text: str, heading: str, default: str) -> str:
    marker = f"## {heading}"
    lines = text.splitlines()
    start_index: int | None = None
    for index, line in enumerate(lines):
        if line.strip() == marker:
            start_index = index + 1
            break
    if start_index is None:
        return default
    end_index = len(lines)
    for index in range(start_index, len(lines)):
        if lines[index].startswith("## "):
            end_index = index
            break
    section = "\n".join(lines[start_index:end_index]).strip()
    if not section:
        return default
    return section


def manual_consensus_section(text: str) -> str:
    section = report_section(text, "Consensus", "")
    for generated_marker in ("### Reviews", "### Decisions", "### Ledger Records"):
        if generated_marker in section:
            section = section.split(generated_marker, 1)[0].strip()
    manual_lines = [
        line
        for line in section.splitlines()
        if line.strip() != CONSENSUS_PLACEHOLDER
    ]
    return "\n".join(manual_lines).strip()


def is_old_generated_summary(section: str) -> bool:
    lines = [line.strip() for line in section.splitlines() if line.strip()]
    if not lines:
        return False
    return lines[0].startswith("Run ID:") and any(line.startswith("- Acceptance:") for line in lines)


def authored_summary_section(text: str) -> str:
    section = report_section(text, "Summary", "")
    if "### Generated Digest" in section:
        section = section.split("### Generated Digest", 1)[0].strip()
    if is_old_generated_summary(section):
        return ""
    manual_lines = [
        line
        for line in section.splitlines()
        if line.strip() != SUMMARY_PLACEHOLDER
    ]
    return "\n".join(manual_lines).strip()


def is_old_generated_changes(section: str) -> bool:
    lines = [line.strip() for line in section.splitlines() if line.strip()]
    if not lines:
        return False
    if lines == ["No changes recorded."]:
        return True
    return lines[0].startswith("- **") and all(
        line.startswith("- **")
        or line.startswith("- Owner:")
        or line.startswith("- Notes:")
        for line in lines
    )


def authored_changes_section(text: str) -> str:
    section = report_section(text, "Changes", "")
    if "### Ledger Records" in section:
        section = section.split("### Ledger Records", 1)[0].strip()
    if is_old_generated_changes(section):
        return ""
    manual_lines = [
        line
        for line in section.splitlines()
        if line.strip() not in {CHANGES_PLACEHOLDER, "No changes recorded."}
    ]
    return "\n".join(manual_lines).strip()


def manual_review_section(text: str) -> str:
    section = report_section(text, "Review", "")
    generated_marker = "### Recorded Reviews"
    if generated_marker in section:
        section = section.split(generated_marker, 1)[0].strip()
    manual_lines = [
        line
        for line in section.splitlines()
        if line.strip() != REVIEW_PLACEHOLDER
    ]
    return "\n".join(manual_lines).strip()


def consensus_field(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        return json.dumps(value, sort_keys=True)
    return str(value)


def inline_code(value: object) -> str:
    text = str(value).replace("`", "\\`")
    return f"`{text}`"


def verification_kind_label(kind: object) -> str:
    if not isinstance(kind, str):
        return "Verification"
    return VERIFICATION_KIND_LABELS.get(kind, kind.replace("_", " ").title())


def record_lines(record: dict[str, object]) -> list[str]:
    result = consensus_field(record.get("result")) or "unknown"
    lines = [f"- **{verification_kind_label(record.get('kind'))}** ({result})"]
    summary = consensus_field(record.get("summary"))
    if summary:
        lines.append(f"  - Summary: {summary}")
    command = consensus_field(record.get("command"))
    if command:
        lines.append(f"  - Command: {inline_code(command)}")
    if record.get("exit_code") is not None:
        lines.append(f"  - Exit Code: {inline_code(record.get('exit_code'))}")
    notes = consensus_field(record.get("notes"))
    if notes:
        lines.append(f"  - Notes: {notes}")
    artifacts = record.get("artifacts")
    if isinstance(artifacts, list):
        artifact_items = [consensus_field(item) for item in artifacts]
        artifact_items = [item for item in artifact_items if item]
        if artifact_items:
            lines.append("  - Artifacts:")
            lines.extend(f"    - {inline_code(item)}" for item in artifact_items)
    return lines


def verification_tally(records: list[dict[str, object]]) -> str:
    if not records:
        return "none recorded"
    counts: dict[str, int] = {}
    for record in records:
        result = consensus_field(record.get("result")) or "unknown"
        counts[result] = counts.get(result, 0) + 1
    ordered_results = [result for result in ALLOWED_VERIFICATION_RESULTS if result in counts]
    ordered_results.extend(sorted(result for result in counts if result not in ALLOWED_VERIFICATION_RESULTS))
    return ", ".join(f"{counts[result]} {result}" for result in ordered_results)


def consensus_status_tally(records: list[dict[str, object]]) -> str:
    if not records:
        return "none"
    counts: dict[str, int] = {}
    for record in records:
        status = consensus_field(record.get("status")) or "unknown"
        counts[status] = counts.get(status, 0) + 1
    ordered_statuses = ("accepted", "rejected", "deferred")
    parts = [f"{counts[status]} {status}" for status in ordered_statuses if status in counts]
    return ", ".join(parts) if parts else "none"


def task_status_tally(records: list[dict[str, object]]) -> str:
    if not records:
        return "none"
    counts: dict[str, int] = {}
    for record in records:
        status = consensus_field(record.get("status")) or "unknown"
        counts[status] = counts.get(status, 0) + 1
    parts = [f"{counts[status]} {status}" for status in TASK_STATUS_ORDER if status in counts]
    parts.extend(f"{counts[status]} {status}" for status in sorted(counts) if status not in TASK_STATUS_ORDER)
    return ", ".join(parts) if parts else "none"


def task_title(record: dict[str, object]) -> str:
    return consensus_field(record.get("title")) or consensus_field(record.get("id")) or "Task record"


def truncate_summary_item(text: str) -> str:
    if len(text) <= SUMMARY_OPEN_ITEM_LIMIT:
        return text
    return text[: SUMMARY_OPEN_ITEM_LIMIT - 1].rstrip() + "…"


def unresolved_items(
    warnings: list[str],
    verification_records: list[dict[str, object]],
    consensus_records: list[dict[str, object]],
    task_records: list[dict[str, object]],
) -> list[str]:
    items = list(warnings)
    for record in verification_records:
        result = consensus_field(record.get("result")) or "unknown"
        if result in UNRESOLVED_VERIFICATION_RESULTS:
            kind = verification_kind_label(record.get("kind"))
            summary = consensus_field(record.get("summary")) or "No summary recorded."
            items.append(f"{kind} ({result}): {summary}")
    for record in consensus_records:
        status = consensus_field(record.get("status")) or "unknown"
        if status in UNRESOLVED_CONSENSUS_STATUSES:
            finding = consensus_field(record.get("finding") or record.get("summary")) or "Consensus record"
            items.append(f"{finding} ({status})")
    for record in task_records:
        status = consensus_field(record.get("status")) or "unknown"
        if status in TASK_RISK_STATUSES:
            items.append(f"{task_title(record)} ({status})")
    return items


def acceptance_decision(status: object, open_risks: list[str]) -> str:
    if status == "accepted":
        if open_risks:
            return f"Accepted, but {len(open_risks)} unresolved item(s) remain — see Risks / Follow-ups."
        return "Accepted based on recorded evidence."
    if status == "rejected":
        return "Rejected based on recorded evidence."
    return "No acceptance decision recorded; this run needs review."


def command_report(args: argparse.Namespace) -> int:
    directory = run_dir(args.repo, args.run_id)
    state = load_json(state_path(directory))
    verifications = ledger_records(directory, "verification")
    review_records = [record for record in verifications if record.get("kind") in REVIEW_KINDS]
    evidence_records = [record for record in verifications if record.get("kind") not in REVIEW_KINDS]
    consensus_records = ledger_records(directory, "consensus")
    task_records = ledger_records(directory, "task")
    warnings = collect_warnings(state)
    open_risks = unresolved_items(warnings, verifications, consensus_records, task_records)
    decision = acceptance_decision(state.get("status"), open_risks)
    sessions = state.get("sessions") if isinstance(state.get("sessions"), list) else []
    existing_report = report_path(directory).read_text(encoding="utf-8") if report_path(directory).exists() else ""
    authored_summary = authored_summary_section(existing_report)
    authored_changes = authored_changes_section(existing_report)
    manual_review = manual_review_section(existing_report)
    manual_consensus = manual_consensus_section(existing_report)
    lines = [
        "# Report",
        "",
        "## Summary",
        "",
    ]
    if authored_summary:
        lines.extend([authored_summary, ""])
    else:
        lines.extend([
            SUMMARY_PLACEHOLDER,
            "",
            "### Generated Digest",
            "",
            f"- Run ID: {state.get('run_id')}",
            f"- Status: {state.get('status')}",
            f"- Generated at: {utc_now()}",
            f"- Acceptance: {decision}",
        ])
        if task_records:
            lines.append(f"- Changes: {len(task_records)} ({task_status_tally(task_records)})")
            lines.extend(f"  - {truncate_summary_item(task_title(record))}" for record in task_records)
        else:
            lines.append("- Changes: none")
        lines.extend([
            f"- Evidence: {verification_tally(evidence_records)}",
            f"- Reviews: {len(review_records)}",
            f"- Consensus: {consensus_status_tally(consensus_records)}",
        ])
        if sessions:
            lines.append(f"- Sessions: {len(sessions)}")
        if open_risks:
            lines.append(f"- Open items ({len(open_risks)}):")
            lines.extend(f"  - {truncate_summary_item(item)}" for item in open_risks)
        else:
            lines.append("- Open items: none")
        lines.append("")
    lines.extend([
        "## Changes",
        "",
    ])
    if authored_changes:
        lines.extend([authored_changes, ""])
    elif task_records:
        lines.extend([CHANGES_PLACEHOLDER, "", "### Ledger Records", ""])
        for record in task_records:
            title = task_title(record)
            status = consensus_field(record.get("status")) or "unknown"
            lines.append(f"- **{title}** ({status})")
            owner = consensus_field(record.get("owner"))
            if owner:
                lines.append(f"  - Owner: {owner}")
            notes = consensus_field(record.get("notes"))
            if notes:
                lines.append(f"  - Notes: {notes}")
        lines.append("")
    else:
        lines.extend([CHANGES_PLACEHOLDER, ""])
    lines.extend([
        "## Evidence",
        "",
    ])
    if evidence_records:
        for record in evidence_records:
            lines.extend(record_lines(record))
    else:
        lines.append(EVIDENCE_PLACEHOLDER)

    lines.extend(["", "## Consensus", ""])
    wrote_consensus_content = False
    if manual_review:
        lines.extend(["### Review Notes", "", manual_review, ""])
        wrote_consensus_content = True
    if manual_consensus:
        lines.extend([manual_consensus, ""])
        wrote_consensus_content = True

    if review_records:
        lines.append("### Reviews")
        lines.append("")
        for record in review_records:
            lines.extend(record_lines(record))
        lines.append("")
        wrote_consensus_content = True

    if consensus_records:
        lines.append("### Decisions")
        lines.append("")
        for record in consensus_records:
            finding = consensus_field(record.get("finding") or record.get("summary")) or "Consensus record"
            lines.append(f"- **Finding:** {finding}")
            root_cause = consensus_field(record.get("root_cause"))
            if root_cause:
                lines.append(f"  - **Root Cause:** {root_cause}")
            resolution = consensus_field(record.get("resolution")) or "Not recorded."
            status = consensus_field(record.get("status")) or "unknown"
            lines.append(f"  - **Resolution:** {resolution}")
            lines.append(f"  - **Status:** {status}")
            evidence = record.get("evidence")
            if isinstance(evidence, list):
                evidence_items = [consensus_field(item) for item in evidence]
                evidence_items = [item for item in evidence_items if item]
                if evidence_items:
                    lines.append("  - **Evidence:**")
                    lines.extend(f"    - {item}" for item in evidence_items)
            else:
                evidence_text = consensus_field(evidence)
                if evidence_text:
                    lines.append(f"  - **Evidence:** {evidence_text}")
        lines.append("")
        wrote_consensus_content = True
    if not wrote_consensus_content:
        lines.extend([CONSENSUS_PLACEHOLDER, ""])

    lines.extend(["## Risks / Follow-ups", ""])
    if open_risks:
        lines.extend(f"- {item}" for item in open_risks)
    else:
        lines.append(RISKS_PLACEHOLDER)

    path = report_path(directory)
    atomic_write_text(path, "\n".join(lines) + "\n")
    print_json({"ok": True, "run_id": args.run_id, "report_path": str(path)})
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Durable ledger CLI for Codex Orchestrator.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    init_parser = subparsers.add_parser("init", help="Create a run ledger.")
    init_parser.add_argument("--repo", required=True, help="Repository root for the run.")
    init_parser.add_argument("--run-id", required=True, type=run_id_type, help="Run id / directory name.")
    init_parser.add_argument("--force", action="store_true", help="Overwrite scaffold files.")
    init_parser.set_defaults(func=command_init)

    status_parser = subparsers.add_parser("status", help="Print compact run status.")
    status_parser.add_argument("--repo", default=".", help="Repository root.")
    status_parser.add_argument("--run-id", required=True, type=run_id_type)
    status_parser.set_defaults(func=command_status)

    verification_parser = subparsers.add_parser("add-verification", help="Append verification evidence.")
    verification_parser.add_argument("--repo", default=".", help="Repository root.")
    verification_parser.add_argument("--run-id", required=True, type=run_id_type)
    verification_parser.add_argument("--kind", required=True, choices=ALLOWED_VERIFICATION_KINDS)
    verification_parser.add_argument("--result", required=True, choices=ALLOWED_VERIFICATION_RESULTS)
    verification_parser.add_argument("--summary", required=True)
    verification_parser.add_argument("--command")
    verification_parser.add_argument("--exit-code", type=int)
    verification_parser.add_argument("--artifact", action="append", default=[])
    verification_parser.add_argument("--notes")
    verification_parser.set_defaults(func=command_add_verification)

    append_parser = subparsers.add_parser("append-event", help="Append a JSON event to ledger.jsonl.")
    append_parser.add_argument("--repo", default=".", help="Repository root.")
    append_parser.add_argument("--run-id", required=True, type=run_id_type)
    append_parser.add_argument("event_json", nargs="?", help="JSON object to append. If omitted, stdin is read.")
    append_parser.add_argument("--event", dest="event_option", help="JSON object to append.")
    append_parser.set_defaults(func=command_append_event)

    worktree_parser = subparsers.add_parser("worktree", help="Create a Codex worktree and register it.")
    worktree_parser.add_argument("--name", required=True, type=name_type, help="Session name, for example codex-a.")
    worktree_parser.add_argument("--repo", default=".", help="Repository root.")
    worktree_parser.add_argument("--run-id", type=run_id_type, help="Run id. Defaults to newest active run.")
    worktree_parser.add_argument("--base", default="main", help="Base ref for the new branch.")
    worktree_parser.add_argument("--branch", help="Branch name. Defaults to codex/<name suffix>.")
    worktree_parser.add_argument("--worktree", help="Worktree path. Defaults to ../repo-<name>.")
    worktree_parser.add_argument("--thread-id", help="Thread id if already known.")
    worktree_parser.add_argument("--mode", choices=("ide", "exec"), default="exec")
    worktree_parser.set_defaults(func=command_worktree)

    report_parser = subparsers.add_parser("report", help="Generate report.md.")
    report_parser.add_argument("--repo", default=".", help="Repository root.")
    report_parser.add_argument("--run-id", required=True, type=run_id_type)
    report_parser.set_defaults(func=command_report)

    return parser


def main() -> int:
    args = build_parser().parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
