from __future__ import annotations

import json
from pathlib import Path

JOURNAL_ENTRY_TYPES = {
    "run_started",
    "task",
    "execution",
    "execution_result",
    "verification",
    "decision",
    "run_closed",
}

TERMINAL_TASK_STATUSES = {"complete", "blocked", "failed"}
TERMINAL_EXECUTION_STATUSES = {"complete", "blocked", "failed"}
VERIFICATION_RESULTS = {"passed", "failed", "inconclusive", "skipped"}


def read_journal(path: Path) -> tuple[list[dict[str, object]], list[str]]:
    records: list[dict[str, object]] = []
    issues: list[str] = []
    if not path.exists():
        return records, [f"missing journal: {path}"]
    try:
        with path.open("r", encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, start=1):
                stripped = line.strip()
                if not stripped:
                    continue
                try:
                    value = json.loads(stripped)
                except json.JSONDecodeError as exc:
                    issues.append(f"line {line_number}: invalid JSON: {exc.msg}")
                    continue
                if not isinstance(value, dict):
                    issues.append(f"line {line_number}: journal entry must be an object")
                    continue
                value["_line"] = line_number
                records.append(value)
    except (OSError, UnicodeError) as exc:
        issues.append(f"could not read journal: {exc}")
    return records, issues


def record_line(record: dict[str, object]) -> str:
    line = record.get("_line")
    return f"line {line}" if isinstance(line, int) else "journal"


def execution_key(record: dict[str, object]) -> tuple[str, str] | None:
    agent = record.get("agent")
    execution = record.get("execution")
    if isinstance(agent, str) and agent and isinstance(execution, str) and execution:
        return agent, execution
    return None


def display_execution(key: tuple[str, str]) -> str:
    return f"{key[0]}/{key[1]}"


def resolve_run_path(run_dir: Path, value: str) -> Path:
    path = Path(value).expanduser()
    return path.resolve() if path.is_absolute() else (run_dir / path).resolve()


def declared_file_exists(run_dir: Path, value: object, *, nonempty: bool = False) -> bool:
    if not isinstance(value, str) or not value:
        return False
    try:
        path = resolve_run_path(run_dir, value)
        return path.is_file() and (not nonempty or path.stat().st_size > 0)
    except (OSError, RuntimeError):
        return False


def check_declared_file(
    run_dir: Path, record: dict[str, object], field: str, issues: list[str]
) -> None:
    if field not in record:
        return
    value = record.get(field)
    if not isinstance(value, str) or not value:
        issues.append(f"{record_line(record)}: {field} must name a file")
        return
    if not declared_file_exists(run_dir, value):
        issues.append(f"{record_line(record)}: referenced {field} file does not exist: {value}")


def validate_run(run_dir: Path) -> dict[str, object]:
    run_dir = run_dir.expanduser().resolve()
    records, issues = read_journal(run_dir / "journal.jsonl")
    warnings: list[str] = []
    non_passing: list[dict[str, object]] = []

    known_records: list[dict[str, object]] = []
    for record in records:
        kind = record.get("type")
        if not isinstance(kind, str) or kind not in JOURNAL_ENTRY_TYPES:
            issues.append(f"{record_line(record)}: unknown journal entry type: {kind!r}")
        else:
            known_records.append(record)

    starts = [record for record in known_records if record.get("type") == "run_started"]
    closures = [record for record in known_records if record.get("type") == "run_closed"]
    if len(starts) != 1:
        issues.append(f"journal must contain exactly one run_started entry; found {len(starts)}")
    elif records and records[0] is not starts[0]:
        issues.append("run_started must be the first journal entry")
    if len(closures) > 1:
        issues.append(f"journal may contain at most one run_closed entry; found {len(closures)}")
    if closures and records and records[-1] is not closures[-1]:
        issues.append("run_closed must be the final journal entry")
    for closure in closures:
        judgment = closure.get("judgment")
        if not isinstance(judgment, str) or judgment not in {"passed", "blocked"}:
            issues.append(f"{record_line(closure)}: run_closed judgment must be passed or blocked")

    tasks: dict[str, dict[str, object]] = {}
    executions: dict[tuple[str, str], dict[str, object]] = {}
    execution_results: dict[tuple[str, str], dict[str, object]] = {}
    seen_ids: dict[str, set[str]] = {"verification": set(), "decision": set()}

    for record in known_records:
        kind = record.get("type")
        if kind in seen_ids:
            record_id = record.get("id")
            if isinstance(record_id, str) and record_id:
                if record_id in seen_ids[kind]:
                    issues.append(f"{record_line(record)}: duplicate {kind} id {record_id}")
                seen_ids[kind].add(record_id)
        if kind == "task":
            task_id = record.get("id")
            if isinstance(task_id, str) and task_id:
                tasks[task_id] = record
            else:
                issues.append(f"{record_line(record)}: task must have a non-empty id")
        elif kind == "execution":
            key = execution_key(record)
            if key is None:
                issues.append(f"{record_line(record)}: execution must identify agent and execution")
            elif key in executions:
                issues.append(
                    f"{record_line(record)}: duplicate execution {display_execution(key)}"
                )
            else:
                executions[key] = record
            check_declared_file(run_dir, record, "prompt", issues)
            check_declared_file(run_dir, record, "events", issues)
        elif kind == "execution_result":
            status = record.get("status")
            if not isinstance(status, str) or status not in TERMINAL_EXECUTION_STATUSES:
                issues.append(
                    f"{record_line(record)}: execution_result status is not terminal: {status}"
                )
            key = execution_key(record)
            if key is None:
                issues.append(
                    f"{record_line(record)}: execution_result must identify agent and execution"
                )
            elif key in execution_results:
                issues.append(
                    f"{record_line(record)}: duplicate execution_result for "
                    f"{display_execution(key)}"
                )
            else:
                execution_results[key] = record
        elif kind == "verification":
            result = record.get("result")
            if not isinstance(result, str) or result not in VERIFICATION_RESULTS:
                issues.append(
                    f"{record_line(record)}: verification result is not recognized: {result}"
                )
            elif result != "passed":
                non_passing.append(
                    {
                        key: record[key]
                        for key in (
                            "id",
                            "task",
                            "criterion",
                            "result",
                            "check",
                            "observation",
                        )
                        if key in record
                    }
                )
            evidence = record.get("evidence", [])
            if not isinstance(evidence, list):
                issues.append(f"{record_line(record)}: evidence must be a list of file paths")
            else:
                for index, value in enumerate(evidence):
                    if not isinstance(value, str) or not value:
                        issues.append(
                            f"{record_line(record)}: evidence[{index}] must name a file: {value!r}"
                        )
                    elif not declared_file_exists(run_dir, value):
                        issues.append(
                            f"{record_line(record)}: referenced evidence[{index}] "
                            f"file does not exist: {value}"
                        )

    for task_id, task in tasks.items():
        status = task.get("status")
        if not isinstance(status, str) or status not in TERMINAL_TASK_STATUSES:
            issues.append(f"task {task_id} is not terminal; latest status is {status!r}")

    for record in known_records:
        kind = record.get("type")
        task_id = record.get("task")
        if kind in {"execution", "execution_result", "verification", "decision"}:
            if "task" in record and (not isinstance(task_id, str) or not task_id):
                issues.append(f"{record_line(record)}: {kind} task reference must be a string")
            elif isinstance(task_id, str) and task_id not in tasks:
                issues.append(f"{record_line(record)}: {kind} references unknown task {task_id}")

    for key, execution in executions.items():
        result = execution_results.get(key)
        if result is None:
            issues.append(f"execution {display_execution(key)} has no terminal execution_result")
            continue
        task_id = execution.get("task")
        result_task = result.get("task")
        if isinstance(task_id, str) and isinstance(result_task, str) and result_task != task_id:
            issues.append(
                f"{record_line(result)}: execution_result task {result_task!r} "
                f"does not match execution task {task_id!r}"
            )
        if int(execution.get("_line", 0)) >= int(result.get("_line", 0)):
            issues.append(
                f"{record_line(result)}: execution {display_execution(key)} "
                "must be recorded before execution_result"
            )
        handoff_values = [
            source.get("handoff") for source in (execution, result) if "handoff" in source
        ]
        handoff_ok = bool(handoff_values) and all(
            declared_file_exists(run_dir, value, nonempty=True) for value in handoff_values
        )
        if not handoff_ok:
            message = f"execution {display_execution(key)} handoff is missing or empty"
            (issues if result.get("status") == "complete" else warnings).append(message)

    for key, result in execution_results.items():
        if key not in executions:
            issues.append(
                f"{record_line(result)}: execution_result references unknown execution "
                f"{display_execution(key)}"
            )
    return {
        "ok": not issues,
        "issues": issues,
        "warnings": warnings,
        "non_passing_verifications": non_passing,
    }
