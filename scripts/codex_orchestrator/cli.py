from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .benchmark import *
from .claims import *
from .contract import *
from .events import *
from .gate import *
from .ledger import *
from .prompts import *
from .report import *
from .resolution import computed_command_hash
from .runmeta import *
from .store import *


def positive_int_type(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("value must be an integer >= 1") from exc
    if str(parsed) != value or parsed < 1:
        raise argparse.ArgumentTypeError("value must be an integer >= 1")
    return parsed


def verification_id_for_record(args: argparse.Namespace, records: list[dict[str, object]]) -> str:
    verification_records = [record for record in records if record.get("type") == "verification"]
    existing_ids = {
        record.get("id")
        for record in verification_records
        if isinstance(record.get("id"), str) and record.get("id")
    }
    if args.id:
        if args.id in existing_ids:
            raise SystemExit(f"ERROR: verification id already exists: {args.id}")
        return args.id

    index = 1
    while f"V{index}" in existing_ids:
        index += 1
    return f"V{index}"


def command_init(args: argparse.Namespace) -> int:
    repo = repo_root(args.repo)
    if not repo.exists() or not repo.is_dir():
        raise SystemExit(f"ERROR: repo does not exist or is not a directory: {repo}")

    directory, created = ensure_run_scaffold(repo, args.run_id, force=args.force)
    print_json({"ok": True, "run_id": args.run_id, "run_dir": str(directory), "created_or_replaced": created})
    return 0


def command_ensure_run(args: argparse.Namespace) -> int:
    repo = repo_root(args.repo)
    if not repo.exists() or not repo.is_dir():
        raise SystemExit(f"ERROR: repo does not exist or is not a directory: {repo}")

    directory, created = ensure_run_scaffold(repo, args.run_id, force=False)
    run_meta = build_run_meta(
        repo=repo,
        run_id=args.run_id,
        plugin_ref=args.plugin_ref,
        benchmark_suite=args.benchmark_suite,
        benchmark_case_id=args.benchmark_case_id,
    )
    upsert = upsert_run_meta(ledger_path(directory), run_meta)
    print_json(
        {
            "ok": True,
            "run_id": args.run_id,
            "run_dir": str(directory),
            "created_or_replaced": created,
            "run_meta_action": upsert["action"],
            "removed_run_meta_duplicates": upsert["removed_duplicates"],
            "run_meta": run_meta,
        }
    )
    return 0


def command_add_verification(args: argparse.Namespace) -> int:
    directory = run_dir(args.repo, args.run_id)
    load_json(state_path(directory))
    records = read_jsonl(ledger_path(directory))
    record: dict[str, object] = {
        "type": "verification",
        "id": verification_id_for_record(args, records),
        "recorded_at": utc_now(),
        "kind": args.kind,
        "result": args.result,
        "summary": args.summary,
    }
    if args.command:
        record["command"] = args.command
        record["command_hash"] = computed_command_hash(args.command)
    if args.exit_code is not None:
        record["exit_code"] = args.exit_code
    if args.artifact:
        record["artifacts"] = args.artifact
    if args.notes:
        record["notes"] = args.notes
    if args.task_id:
        record["task_id"] = args.task_id
    if args.covers_tasks:
        record["covers_tasks"] = args.covers_tasks
    if args.scope:
        record["scope"] = args.scope
    if args.finding_id:
        record["finding_id"] = args.finding_id
    if args.acceptance_test:
        record["acceptance_test"] = True
    if args.attempt_count is not None:
        record["attempt_count"] = args.attempt_count
    validate_ledger_event(record)
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
    validate_ledger_event(event)
    append_jsonl(ledger_path(directory), event)
    print_json({"ok": True, "ledger_path": str(ledger_path(directory)), "event": event})
    return 0


def command_claim_files(args: argparse.Namespace) -> int:
    directory = run_dir(args.repo, args.run_id)
    load_json(state_path(directory))
    record: dict[str, object] = {
        "type": "file_claimed",
        "task_id": args.task_id,
        "agent": args.agent,
        "allow": args.allow,
    }
    if args.forbid:
        record["forbid"] = args.forbid
    validate_ledger_event(record)
    append_jsonl(ledger_path(directory), record)
    print_json({"ok": True, "ledger_path": str(ledger_path(directory)), "event": record})
    return 0


def command_check_conflicts(args: argparse.Namespace) -> int:
    directory = run_dir(args.repo, args.run_id)
    load_json(state_path(directory))
    report = file_claim_conflict_report(read_jsonl(ledger_path(directory)))
    print_json(report)
    return 0 if report["ok"] else 1


def command_gate(args: argparse.Namespace) -> int:
    directory = run_dir(args.repo, args.run_id)
    state = load_json(state_path(directory))
    records, diagnostics = read_jsonl_with_warnings(ledger_path(directory))
    blocking = gate_blocking_reasons(directory, records, diagnostics)
    warnings = low_confidence_warnings(state) + gate_warning_reasons(records)
    payload = {
        "ok": not blocking,
        "blocking": blocking,
        "warnings": warnings,
    }
    record = {"type": "gate_result", "ok": payload["ok"], "blocking": blocking, "warnings": payload["warnings"]}
    validate_ledger_event(record)
    append_jsonl(ledger_path(directory), record)
    print_json(payload)
    return 0 if payload["ok"] else 1


def command_doctor(args: argparse.Namespace) -> int:
    directory = run_dir(args.repo, args.run_id)
    state = load_json(state_path(directory))
    records, diagnostics = read_jsonl_with_warnings(ledger_path(directory))
    issues = doctor_issues(directory, state, records, diagnostics)
    print_json({"ok": not issues, "issues": issues})
    return 0 if not issues else 1


def command_status(args: argparse.Namespace) -> int:
    directory = run_dir(args.repo, args.run_id)
    state = load_json(state_path(directory))
    sessions = state.get("sessions") if isinstance(state.get("sessions"), list) else []
    ledger, ledger_diagnostics = read_jsonl_with_warnings(ledger_path(directory))
    verification = latest_verification_from_records(ledger)
    warnings = collect_warnings(state, ledger_diagnostics)
    payload = {
        "run_id": state.get("run_id"),
        "status": state.get("status"),
        "repo": state.get("repo"),
        "session_count": len(sessions),
        "sessions": sessions[-5:],
        "latest_verification": verification,
        "warnings": warnings,
        "recommended_next_action": recommended_next_action(state, verification, warnings),
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


def command_report(args: argparse.Namespace) -> int:
    directory = run_dir(args.repo, args.run_id)
    state = load_json(state_path(directory))
    existing_report = report_path(directory).read_text(encoding="utf-8") if report_path(directory).exists() else ""
    ledger, ledger_diagnostics = read_jsonl_with_warnings(ledger_path(directory))
    path = report_path(directory)
    report = render_report(
        state=state,
        ledger=ledger,
        existing_report=existing_report,
        warnings=collect_warnings(state, ledger_diagnostics),
        generated_at=utc_now(),
    )
    atomic_write_text(path, report)
    missing = strict_report_missing_evidence(state=state, ledger=ledger, report=report) if args.strict else []
    payload = {"ok": not missing, "run_id": args.run_id, "report_path": str(path)}
    if missing:
        payload["missing"] = missing
    print_json(payload)
    return 1 if missing else 0


def command_render_prompt(args: argparse.Namespace) -> int:
    directory = run_dir(args.repo, args.run_id)
    load_json(state_path(directory))
    record = task_created_record(read_jsonl(ledger_path(directory)), args.task_id)
    template_path = prompt_template_path(args.kind)
    if not template_path.exists():
        raise SystemExit(f"ERROR: missing prompt template: {template_path}")
    rendered = render_prompt_template(template_path.read_text(encoding="utf-8"), prompt_context(record))
    if args.out:
        output_path = Path(args.out).expanduser()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(output_path, rendered)
    else:
        sys.stdout.write(rendered)
    return 0


def command_benchmark(args: argparse.Namespace) -> int:
    directory = run_dir(args.repo, args.run_id)
    state = load_json(state_path(directory))
    ledger, ledger_diagnostics = read_jsonl_with_warnings(ledger_path(directory))
    run_meta = latest_record(ledger, "run_meta") or {}
    repo = repo_root(args.repo)
    sessions = state.get("sessions") if isinstance(state.get("sessions"), list) else []
    gate_passed = latest_gate_passed(ledger)
    score = report_completeness_score(state, ledger)
    plugin_checkout = plugin_root()
    passed = args.passed if args.passed is not UNSET else gate_passed
    payload: dict[str, object] = {
        "suite": args.suite or string_or_none(run_meta.get("benchmark_suite")),
        "case_id": args.case_id or string_or_none(run_meta.get("benchmark_case_id")),
        "plugin_ref": args.plugin_ref or string_or_none(run_meta.get("plugin_git_sha")) or detect_git_sha(plugin_checkout),
        "repo_commit": string_or_none(run_meta.get("repo_commit")) or detect_git_sha(repo),
        "passed": passed,
        "wall_seconds": None,
        "claude_turns": None,
        "codex_sessions": len(sessions),
        "codex_reviews": sum(1 for record in ledger if is_final_review_verification(record)),
        "manual_interventions": None,
        "prompt_log_pairs_complete": prompt_log_pairs_complete(ledger),
        "ledger_errors": len(ledger_diagnostics),
        "gate_passed": gate_passed,
        "report_score": score["total"],
        "external_score": None,
    }
    validate_benchmark_result(payload)
    path = benchmark_path(directory)
    write_json(path, payload, force=True)
    print_json({"ok": True, "run_id": args.run_id, "benchmark_path": str(path), "benchmark": payload})
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Durable ledger CLI for Codex Orchestrator.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    init_parser = subparsers.add_parser("init", help="Create a run ledger.")
    init_parser.add_argument("--repo", required=True, help="Repository root for the run.")
    init_parser.add_argument("--run-id", required=True, type=run_id_type, help="Run id / directory name.")
    init_parser.add_argument("--force", action="store_true", help="Overwrite scaffold files.")
    init_parser.set_defaults(func=command_init)

    ensure_parser = subparsers.add_parser("ensure-run", help="Create a run scaffold and upsert run metadata.")
    ensure_parser.add_argument("--repo", default=".", help="Repository root.")
    ensure_parser.add_argument("--run-id", required=True, type=run_id_type, help="Run id / directory name.")
    ensure_parser.add_argument("--plugin-ref", help="Plugin git SHA or ref to record.")
    ensure_parser.add_argument("--benchmark-suite", help="Benchmark suite name.")
    ensure_parser.add_argument("--benchmark-case-id", help="Benchmark case id.")
    ensure_parser.set_defaults(func=command_ensure_run)

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
    verification_parser.add_argument("--id")
    verification_parser.add_argument("--command")
    verification_parser.add_argument("--exit-code", type=int)
    verification_parser.add_argument("--artifact", action="append", default=[])
    verification_parser.add_argument("--notes")
    verification_parser.add_argument("--task-id", help="Scope this verification to a task id.")
    verification_parser.add_argument("--finding-id")
    verification_parser.add_argument("--acceptance-test", action="store_true")
    verification_parser.add_argument("--attempt-count", type=positive_int_type)
    verification_parser.add_argument(
        "--covers-tasks",
        action="append",
        default=[],
        help="Extra task id this verification also covers; repeatable.",
    )
    verification_parser.add_argument("--scope", choices=VERIFICATION_SCOPE_ORDER)
    verification_parser.set_defaults(func=command_add_verification)

    append_parser = subparsers.add_parser("append-event", help="Append a schema-checked JSON event to ledger.jsonl.")
    append_parser.add_argument("--repo", default=".", help="Repository root.")
    append_parser.add_argument("--run-id", required=True, type=run_id_type)
    append_parser.add_argument("event_json", nargs="?", help="JSON object to append. If omitted, stdin is read.")
    append_parser.add_argument("--event", dest="event_option", help="JSON object to append.")
    append_parser.set_defaults(func=command_append_event)

    claim_parser = subparsers.add_parser("claim-files", help="Append a writable file-claim event.")
    claim_parser.add_argument("--repo", default=".", help="Repository root.")
    claim_parser.add_argument("--run-id", required=True, type=run_id_type)
    claim_parser.add_argument("--task-id", required=True)
    claim_parser.add_argument("--agent", required=True)
    claim_parser.add_argument("--allow", required=True, action="append", help="Writable glob. Repeat for multiple globs.")
    claim_parser.add_argument("--forbid", action="append", default=[], help="Forbidden glob. Repeat for multiple globs.")
    claim_parser.set_defaults(func=command_claim_files)

    conflicts_parser = subparsers.add_parser("check-conflicts", help="Check active file claims for writable overlap.")
    conflicts_parser.add_argument("--repo", default=".", help="Repository root.")
    conflicts_parser.add_argument("--run-id", required=True, type=run_id_type)
    conflicts_parser.set_defaults(func=command_check_conflicts)

    gate_parser = subparsers.add_parser("gate", help="Evaluate whether a run is ready for acceptance.")
    gate_parser.add_argument("--repo", default=".", help="Repository root.")
    gate_parser.add_argument("--run-id", required=True, type=run_id_type)
    gate_parser.set_defaults(func=command_gate)

    doctor_parser = subparsers.add_parser("doctor", help="Check run ledger integrity without mutating it.")
    doctor_parser.add_argument("--repo", default=".", help="Repository root.")
    doctor_parser.add_argument("--run-id", required=True, type=run_id_type)
    doctor_parser.set_defaults(func=command_doctor)

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
    report_parser.add_argument("--strict", action="store_true", help="Fail if required report evidence is missing.")
    report_parser.set_defaults(func=command_report)

    prompt_parser = subparsers.add_parser("render-prompt", help="Render a Codex task or review prompt.")
    prompt_parser.add_argument("--repo", default=".", help="Repository root.")
    prompt_parser.add_argument("--run-id", required=True, type=run_id_type)
    prompt_parser.add_argument("--task-id", required=True)
    prompt_parser.add_argument("--kind", required=True, choices=tuple(PROMPT_TEMPLATE_FILES))
    prompt_parser.add_argument("--out", help="Write the rendered prompt to this file instead of stdout.")
    prompt_parser.set_defaults(func=command_render_prompt)

    benchmark_parser = subparsers.add_parser("benchmark", help="Write benchmark.json for a run.")
    benchmark_parser.add_argument("--repo", default=".", help="Repository root.")
    benchmark_parser.add_argument("--run-id", required=True, type=run_id_type)
    benchmark_parser.add_argument("--suite", help="Benchmark suite name.")
    benchmark_parser.add_argument("--case-id", help="Benchmark case id.")
    benchmark_parser.add_argument("--plugin-ref", help="Plugin git SHA or ref.")
    benchmark_parser.add_argument(
        "--passed",
        default=UNSET,
        type=nullable_bool_type,
        help="Benchmark pass status: true, false, or null.",
    )
    benchmark_parser.set_defaults(func=command_benchmark)

    return parser


def main() -> int:
    args = build_parser().parse_args()
    return args.func(args)
