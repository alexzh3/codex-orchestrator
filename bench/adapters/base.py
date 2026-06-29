from __future__ import annotations

import json
import os
from pathlib import Path

from bench.runners.run_claude import build_claude_argv
from bench.runners.run_claude import run_case as run_claude_case
from codex_orch import validate_benchmark_result


TaskDescriptor = dict[str, object]


class Adapter:
    name = ""
    display_name = ""
    real_infra = ""
    dry_run_focus = "benchmark task"
    max_budget_usd = 0
    dataset_env_var = ""
    dataset_default = ""
    dataset_layout = ""
    issue_ref = ""
    task_file_candidates: tuple[str, ...] = ("tasks.jsonl", "tasks.json")
    grader_command_env_var = ""
    grader_infra = ""
    default_start_ref = "main"
    default_timeout_seconds = 3600
    default_max_turns = 40

    def iter_tasks(self, count: int, selection: str, *, dry_run: bool) -> list[TaskDescriptor]:
        if count < 0:
            raise ValueError("count must be non-negative")
        if not selection:
            raise ValueError("selection must be non-empty")
        if not dry_run:
            dataset_dir = self._dataset_dir()
            task_files = self._task_files(dataset_dir)
            raw_tasks = self._load_task_files(task_files)
            if not raw_tasks:
                raise self._dataset_error(dataset_dir, "no task descriptors were found")
            tasks = [self._normalize_task(raw_task, dataset_dir, selection) for raw_task in raw_tasks]
            selected = self._select_tasks(tasks, selection)
            if len(selected) < count:
                raise self._dataset_error(
                    dataset_dir,
                    f"only {len(selected)} task descriptors are available for requested count {count}",
                )
            return selected[:count]
        return [self._dry_run_task(index, selection) for index in range(1, count + 1)]

    def run_task(
        self,
        task: TaskDescriptor,
        plugin_ref: str,
        *,
        dry_run: bool,
        repo_root: Path,
        work_dir: Path,
    ) -> dict[str, object]:
        if not dry_run:
            case = self._case_from_task(task, work_dir)
            try:
                runner_result = self._run_claude_case(
                    case,
                    plugin_ref,
                    repo_root=repo_root,
                    work_dir=work_dir,
                )
            except FileNotFoundError as exc:
                raise RuntimeError(
                    f"{self.display_name} real run could not start {exc.filename!r}; "
                    f"install the Claude CLI and required infra ({self.real_infra})."
                ) from exc
            except RuntimeError:
                raise
            except Exception as exc:
                raise RuntimeError(
                    f"{self.display_name} real run failed before grading; "
                    f"required infra: {self.real_infra}; detail: {exc}"
                ) from exc

            grade = self._grade(task, work_dir=work_dir, runner_result=runner_result)
            return self._merge_result(task, plugin_ref, runner_result, grade)

        task_id = _string_field(task, "id")
        selection = _string_field(task, "selection")
        prompt = _string_field(task, "prompt")
        case = {
            "id": task_id,
            "suite": self.name,
            "prompt": prompt,
            "max_budget_usd": self.max_budget_usd,
        }
        argv = build_claude_argv(case, plugin_ref, work_dir=work_dir)
        fingerprint = _fingerprint(f"{self.name}:{task_id}")
        tests_passed = fingerprint % 6 != 0
        gate_passed = fingerprint % 4 != 0
        payload: dict[str, object] = {
            "suite": self.name,
            "case_id": task_id,
            "plugin_ref": plugin_ref,
            "repo_commit": f"dry-run:{self.name}",
            "passed": tests_passed,
            "wall_seconds": round((fingerprint % 37) / 1000, 6),
            "claude_turns": 1 + (fingerprint % 5),
            "codex_sessions": 1 + (fingerprint % 3),
            "codex_reviews": 1 if gate_passed else 0,
            "manual_interventions": fingerprint % 2,
            "prompt_log_pairs_complete": fingerprint % 5 != 0,
            "ledger_errors": 0,
            "gate_passed": gate_passed,
            "report_score": round(0.55 + ((fingerprint % 41) / 100), 4),
            "external_score": {
                "benchmark": self.name,
                "dry_run": True,
                "selection": selection,
                "tests_passed": tests_passed,
                "task_id": task_id,
                "required_infra": self.real_infra,
                "claude_argv": argv,
            },
        }
        validate_benchmark_result(payload)
        return payload

    def _dataset_dir(self) -> Path:
        raw_path = os.environ.get(self.dataset_env_var) if self.dataset_env_var else None
        path = Path(raw_path or self.dataset_default).expanduser()
        return path

    def _dataset_error(self, dataset_dir: Path, reason: str) -> RuntimeError:
        return RuntimeError(
            f"{self.display_name} dataset is unavailable: {reason}. "
            f"Set {self.dataset_env_var} to a local dataset directory. "
            f"Expected layout: {self.dataset_layout}. "
            f"Required infra: {self.real_infra}. "
            f"Checked: {dataset_dir}. Tracking issue: {self.issue_ref}."
        )

    def _task_files(self, dataset_dir: Path) -> list[Path]:
        if not dataset_dir.is_dir():
            raise self._dataset_error(dataset_dir, "directory is missing")
        files = [dataset_dir / relative for relative in self.task_file_candidates if (dataset_dir / relative).is_file()]
        if not files:
            raise self._dataset_error(dataset_dir, "directory contains no supported task file")
        return files

    def _load_task_files(self, task_files: list[Path]) -> list[dict[str, object]]:
        tasks: list[dict[str, object]] = []
        for task_file in task_files:
            tasks.extend(_load_task_file(task_file))
        return tasks

    def _normalize_task(self, raw_task: dict[str, object], dataset_dir: Path, selection: str) -> TaskDescriptor:
        task = dict(raw_task)
        task_id = _task_id(task)
        prompt = _task_prompt(task, task_id)
        task["id"] = task_id
        task["suite"] = self.name
        task["benchmark"] = self.name
        task["selection"] = selection
        task["prompt"] = prompt
        task["_dataset_dir"] = str(dataset_dir)
        if "files_allowed" not in task:
            allowed = task.get("allowed_files")
            task["files_allowed"] = allowed if isinstance(allowed, list) else ["*", "**/*"]
        return task

    def _select_tasks(self, tasks: list[TaskDescriptor], selection: str) -> list[TaskDescriptor]:
        if selection != "lowest_success_rate":
            ordered = sorted(tasks, key=lambda task: _string_field(task, "id"))
            return _annotate_selection(
                ordered,
                f"selection {selection!r} is not benchmark-native; used stable task-id ordering",
            )

        if any(_success_rate(task) is not None for task in tasks):
            return sorted(
                tasks,
                key=lambda task: (
                    1 if _success_rate(task) is None else 0,
                    _success_rate(task) if _success_rate(task) is not None else 2.0,
                    _string_field(task, "id"),
                ),
            )

        if any(_difficulty_score(task) is not None for task in tasks):
            ordered = sorted(
                tasks,
                key=lambda task: (
                    1 if _difficulty_score(task) is None else 0,
                    -(_difficulty_score(task) or 0.0),
                    _string_field(task, "id"),
                ),
            )
            return _annotate_selection(
                ordered,
                "dataset has no success-rate field; selected highest difficulty first",
            )

        ordered = sorted(tasks, key=lambda task: _string_field(task, "id"))
        return _annotate_selection(
            ordered,
            "dataset has no success-rate or difficulty field; used stable task-id ordering",
        )

    def _case_from_task(self, task: TaskDescriptor, work_dir: Path) -> dict[str, object]:
        task_id = _string_field(task, "id")
        files_allowed = task.get("files_allowed")
        if files_allowed is None:
            files_allowed = ["*", "**/*"]
        return {
            "id": task_id,
            "suite": self.name,
            "start_ref": _string_value(task.get("start_ref")) or _string_value(task.get("base_ref")) or self.default_start_ref,
            "prompt": _string_field(task, "prompt"),
            "files_allowed": _string_list_value(files_allowed, field="files_allowed"),
            "acceptance": {
                "command": self._acceptance_command(task, work_dir),
            },
            "timeout_seconds": _int_value(task.get("timeout_seconds"), self.default_timeout_seconds),
            "max_turns": _int_value(task.get("max_turns"), self.default_max_turns),
            "max_budget_usd": _number_value(task.get("max_budget_usd"), self.max_budget_usd),
        }

    def _acceptance_command(self, task: TaskDescriptor, work_dir: Path) -> str:
        template = ""
        acceptance = task.get("acceptance")
        if isinstance(acceptance, dict):
            template = _string_value(acceptance.get("command")) or ""
        if not template:
            template = (
                _string_value(task.get("acceptance_command"))
                or _string_value(task.get("grader_command"))
                or _string_value(task.get("test_command"))
                or ""
            )
        if not template and self.grader_command_env_var:
            template = os.environ.get(self.grader_command_env_var, "")
        if not template:
            raise RuntimeError(
                f"{self.display_name} real run needs a grader command. "
                f"Put acceptance.command or grader_command in the task descriptor, "
                f"or set {self.grader_command_env_var}. Required infra: {self.real_infra}; "
                f"grader: {self.grader_infra}. "
                f"Tracking issue: {self.issue_ref}."
            )
        return _format_command(template, task, work_dir)

    def _run_claude_case(
        self,
        case: dict[str, object],
        plugin_ref: str,
        *,
        repo_root: Path,
        work_dir: Path,
    ) -> dict[str, object]:
        return run_claude_case(case, plugin_ref, dry_run=False, repo_root=repo_root, work_dir=work_dir)

    def _grade(
        self,
        task: TaskDescriptor,
        *,
        work_dir: Path,
        runner_result: dict[str, object],
    ) -> dict[str, object]:
        del task, work_dir
        external_score = runner_result.get("external_score")
        if not isinstance(external_score, dict):
            raise RuntimeError(f"{self.display_name} grader result is unavailable in the runner payload.")

        exit_code = external_score.get("acceptance_exit_code")
        grader_exit_code = exit_code if type(exit_code) is int else None
        if grader_exit_code in (126, 127):
            raise RuntimeError(
                f"{self.display_name} grader command could not start (exit {grader_exit_code}). "
                f"Install {self.grader_infra} or set {self.grader_command_env_var}. "
                f"Command: {external_score.get('acceptance_command')}"
            )

        return {
            "benchmark": self.name,
            "tests_passed": grader_exit_code == 0,
            "grader_exit_code": grader_exit_code,
            "grader_command": external_score.get("acceptance_command"),
            "grader_timed_out": external_score.get("acceptance_timed_out") is True,
            "claude_timed_out": external_score.get("timed_out") is True,
            "required_infra": self.grader_infra,
        }

    def _merge_result(
        self,
        task: TaskDescriptor,
        plugin_ref: str,
        runner_result: dict[str, object],
        grade: dict[str, object],
    ) -> dict[str, object]:
        task_id = _string_field(task, "id")
        runner_passed = runner_result.get("passed") is True
        grade_passed = _grade_passed(grade, self.display_name)
        external_score = dict(grade)
        external_score.setdefault("benchmark", self.name)
        external_score.setdefault("task_id", task_id)
        external_score["run_claude_passed"] = runner_passed
        external_score["run_claude_external_score"] = runner_result.get("external_score")

        payload: dict[str, object] = {
            "suite": self.name,
            "case_id": task_id,
            "plugin_ref": plugin_ref,
            "repo_commit": runner_result.get("repo_commit"),
            "passed": runner_passed and grade_passed,
            "wall_seconds": _number_value(runner_result.get("wall_seconds"), 0.0),
            "claude_turns": _int_value(runner_result.get("claude_turns"), 0),
            "codex_sessions": _int_value(runner_result.get("codex_sessions"), 0),
            "codex_reviews": _int_value(runner_result.get("codex_reviews"), 0),
            "manual_interventions": _int_value(runner_result.get("manual_interventions"), 0),
            "prompt_log_pairs_complete": runner_result.get("prompt_log_pairs_complete") is True,
            "ledger_errors": _int_value(runner_result.get("ledger_errors"), 0),
            "gate_passed": runner_result.get("gate_passed") if isinstance(runner_result.get("gate_passed"), bool) else None,
            "report_score": min(1.0, max(0.0, _number_value(runner_result.get("report_score"), 0.0))),
            "external_score": external_score,
        }
        validate_benchmark_result(payload)
        return payload

    def _dry_run_task(self, index: int, selection: str) -> TaskDescriptor:
        task_id = f"{self.name}-dry-{index:03d}"
        return {
            "id": task_id,
            "suite": self.name,
            "benchmark": self.name,
            "selection": selection,
            "prompt": (
                f"Dry-run {self.display_name} task {index:03d}: "
                f"implement the workflow for a {selection} {self.dry_run_focus}."
            ),
        }


def _string_field(payload: dict[str, object], field: str) -> str:
    value = payload.get(field)
    if not isinstance(value, str) or not value:
        raise ValueError(f"task is missing non-empty string field {field}")
    return value


def _string_value(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def _int_value(value: object, default: int) -> int:
    return value if type(value) is int and value >= 0 else default


def _number_value(value: object, default: int | float) -> int | float:
    return value if isinstance(value, (int, float)) and value >= 0 else default


def _string_list_value(value: object, *, field: str) -> list[str]:
    if not isinstance(value, list):
        raise ValueError(f"task field {field} must be a list")
    result: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item:
            raise ValueError(f"task field {field} entries must be non-empty strings")
        result.append(item)
    return result


def _load_task_file(path: Path) -> list[dict[str, object]]:
    if path.suffix == ".jsonl":
        return _load_jsonl_tasks(path)
    if path.suffix == ".json":
        payload = json.loads(path.read_text(encoding="utf-8"))
        return _tasks_from_json_payload(payload, path)
    raise ValueError(f"unsupported task descriptor file: {path}")


def _load_jsonl_tasks(path: Path) -> list[dict[str, object]]:
    tasks: list[dict[str, object]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        payload = json.loads(line)
        if not isinstance(payload, dict):
            raise ValueError(f"{path}:{line_number} must contain a JSON object")
        tasks.append(payload)
    return tasks


def _tasks_from_json_payload(payload: object, path: Path) -> list[dict[str, object]]:
    if isinstance(payload, list):
        return [_json_task(item, path) for item in payload]
    if isinstance(payload, dict):
        for key in ("tasks", "instances", "examples", "cases"):
            value = payload.get(key)
            if isinstance(value, list):
                return [_json_task(item, path) for item in value]
        if _looks_like_task(payload):
            return [payload]
        if all(isinstance(item, dict) for item in payload.values()):
            return [_json_task(item, path) for item in payload.values()]
    raise ValueError(f"{path} must contain a task object, a task list, or a keyed task collection")


def _json_task(value: object, path: Path) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ValueError(f"{path} task entries must be JSON objects")
    return value


def _looks_like_task(value: dict[str, object]) -> bool:
    return any(key in value for key in ("id", "task_id", "instance_id", "name", "prompt", "problem_statement"))


def _task_id(task: dict[str, object]) -> str:
    for field in ("id", "task_id", "instance_id", "case_id", "name"):
        value = _string_value(task.get(field))
        if value:
            return value
    raise ValueError("task descriptor is missing a non-empty id/task_id/instance_id/name field")


def _task_prompt(task: dict[str, object], task_id: str) -> str:
    for field in ("prompt", "instructions", "instruction", "problem_statement", "description", "task"):
        value = _string_value(task.get(field))
        if value:
            return value
    raise ValueError(
        f"task {task_id!r} is missing prompt text "
        "(expected prompt/instructions/problem_statement/description)"
    )


def _lookup(task: dict[str, object], names: tuple[str, ...]) -> object:
    for name in names:
        if name in task:
            return task[name]
    metadata = task.get("metadata")
    if isinstance(metadata, dict):
        for name in names:
            if name in metadata:
                return metadata[name]
    return None


def _success_rate(task: dict[str, object]) -> float | None:
    value = _lookup(
        task,
        (
            "success_rate",
            "pass_rate",
            "solve_rate",
            "baseline_success_rate",
            "baseline_pass_rate",
            "resolved_rate",
        ),
    )
    return _rate_value(value)


def _rate_value(value: object) -> float | None:
    if isinstance(value, (int, float)):
        rate = float(value)
    elif isinstance(value, str):
        raw = value.strip()
        percent = raw.endswith("%")
        if percent:
            raw = raw[:-1].strip()
        try:
            rate = float(raw)
        except ValueError:
            return None
        if percent:
            rate /= 100
    else:
        return None
    if rate > 1.0 and rate <= 100.0:
        rate /= 100
    if rate < 0.0:
        return None
    return rate


def _difficulty_score(task: dict[str, object]) -> float | None:
    value = _lookup(task, ("difficulty_score", "difficulty", "difficulty_band", "hardness", "fail_rate"))
    if isinstance(value, (int, float)):
        return float(value)
    if not isinstance(value, str):
        return None
    normalized = value.lower().replace("_", "-").replace(" ", "-")
    if "expert" in normalized or "hardest" in normalized:
        return 5.0
    if "hard" in normalized:
        return 4.0
    if "medium" in normalized or "moderate" in normalized:
        return 3.0
    if "easy" in normalized:
        return 1.0
    return None


def _annotate_selection(tasks: list[TaskDescriptor], note: str) -> list[TaskDescriptor]:
    for task in tasks:
        task["selection_note"] = note
    return tasks


def _format_command(template: str, task: TaskDescriptor, work_dir: Path) -> str:
    values: dict[str, object] = {
        "id": _string_field(task, "id"),
        "task_id": _string_field(task, "id"),
        "case_id": _string_field(task, "id"),
        "work_dir": str(work_dir),
        "dataset_dir": _string_value(task.get("_dataset_dir")) or "",
    }
    for key, value in task.items():
        if key.isidentifier() and isinstance(value, (str, int, float, bool)):
            values[key] = value
    try:
        return template.format_map(_FormatValues(values))
    except KeyError as exc:
        raise RuntimeError(f"grader command references unknown placeholder {{{exc.args[0]}}}") from exc


class _FormatValues(dict[str, object]):
    def __missing__(self, key: str) -> object:
        raise KeyError(key)


def _grade_passed(grade: dict[str, object], display_name: str) -> bool:
    for field in ("tests_passed", "passed", "success"):
        value = grade.get(field)
        if isinstance(value, bool):
            return value
    raise RuntimeError(
        f"{display_name} grader hook returned no boolean tests_passed/passed/success field"
    )


def _fingerprint(value: str) -> int:
    return sum((index + 1) * ord(char) for index, char in enumerate(value))
