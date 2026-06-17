#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
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

DEFAULT_VERIFICATION_POLICY = {
    "required": [
        "git diff review",
        "test command",
        "artifact manifest check when artifacts are produced",
    ],
    "forbidden": [
        "delete tests to pass",
        "shrink validation ranges without justification",
        "accept training/RL changes on a single stochastic pass",
    ],
    "nondeterministic_rollouts": [
        "seeded determinism where supported",
        "metric-threshold checks on eval rollouts",
        "regression bands on reward/return instead of equality assertions",
    ],
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def print_json(payload: object) -> None:
    print(json.dumps(payload, indent=2, sort_keys=True))


def run_id_type(value: str) -> str:
    if not value or value in {".", ".."} or "/" in value or "\\" in value:
        raise argparse.ArgumentTypeError("run id must be a single path segment")
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
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n")


def initial_state(repo: Path, run_id: str) -> dict[str, object]:
    return {
        "run_id": run_id,
        "repo": str(repo),
        "created_at": utc_now(),
        "status": "active",
        "sessions": [],
        "verification_policy": DEFAULT_VERIFICATION_POLICY,
    }


def ledger_records(directory: Path, record_type: str | None = None) -> list[dict[str, object]]:
    records = read_jsonl(ledger_path(directory))
    if record_type is None:
        return records
    return [record for record in records if record.get("type") == record_type]


def latest_verification(directory: Path) -> dict[str, object] | None:
    records = ledger_records(directory, "verification")
    return records[-1] if records else None


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
            "# Report\n\n## Review\n\n## Consensus\n\n## Final Report\n\n",
            force=args.force,
        ),
    }
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


def report_section(text: str, heading: str, default: str) -> str:
    marker = f"## {heading}"
    start = text.find(marker)
    if start == -1:
        return default
    start += len(marker)
    next_heading = text.find("\n## ", start)
    section = text[start: next_heading if next_heading != -1 else None].strip()
    if not section:
        return default
    return section


def manual_consensus_section(text: str) -> str:
    section = report_section(text, "Consensus", "No consensus decisions recorded.")
    generated_marker = "### Ledger Records"
    if generated_marker in section:
        section = section.split(generated_marker, 1)[0].strip()
    return section or "No consensus decisions recorded."


def command_report(args: argparse.Namespace) -> int:
    directory = run_dir(args.repo, args.run_id)
    state = load_json(state_path(directory))
    verifications = ledger_records(directory, "verification")
    consensus_records = ledger_records(directory, "consensus")
    warnings = collect_warnings(state)
    existing_report = report_path(directory).read_text(encoding="utf-8") if report_path(directory).exists() else ""
    lines = [
        "# Report",
        "",
        "## Review",
        "",
        report_section(existing_report, "Review", "No review notes recorded."),
        "",
        "## Consensus",
        "",
        manual_consensus_section(existing_report),
        "",
    ]
    if consensus_records:
        lines.append("### Ledger Records")
        lines.append("")
        for record in consensus_records:
            lines.append(f"- {record.get('summary') or record.get('finding') or record}")
        lines.append("")

    lines.extend([
        "## Final Report",
        "",
        f"Run ID: {state.get('run_id')}",
        f"Status: {state.get('status')}",
        f"Generated at: {utc_now()}",
        "",
        "### Sessions",
        "",
    ])
    sessions = state.get("sessions") if isinstance(state.get("sessions"), list) else []
    if sessions:
        for session in sessions:
            if isinstance(session, dict):
                lines.append(
                    "- {name}: {status} ({mode})".format(
                        name=session.get("name") or "codex",
                        status=session.get("status") or "unknown",
                        mode=session.get("mode") or session.get("event_source") or "unknown",
                    )
                )
    else:
        lines.append("No sessions recorded.")

    lines.extend(["", "### Verification Evidence", ""])
    if verifications:
        for record in verifications:
            command = f" command={record.get('command')!r}" if record.get("command") else ""
            exit_code = f" exit_code={record.get('exit_code')}" if record.get("exit_code") is not None else ""
            lines.append(
                "- {kind}: {result}{command}{exit_code} - {summary}".format(
                    kind=record.get("kind"),
                    result=record.get("result"),
                    command=command,
                    exit_code=exit_code,
                    summary=record.get("summary") or "",
                )
            )
    else:
        lines.append("No verification evidence recorded.")

    lines.extend(["", "### Risks / Unresolved Items", ""])
    if warnings:
        lines.extend(f"- {warning}" for warning in warnings)
    else:
        lines.append("No parser warnings or unresolved items recorded.")

    lines.extend(["", "### Acceptance Decision", ""])
    if state.get("status") == "accepted":
        lines.append("Accepted based on recorded evidence.")
    elif state.get("status") == "rejected":
        lines.append("Rejected based on recorded evidence.")
    else:
        lines.append("No acceptance decision recorded; this run needs review.")

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
