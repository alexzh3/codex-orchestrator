from __future__ import annotations

from pathlib import Path

from bench.runners.run_claude import build_claude_argv
from codex_orch import validate_benchmark_result


TaskDescriptor = dict[str, object]


class Adapter:
    name = ""
    display_name = ""
    real_infra = ""
    dry_run_focus = "benchmark task"
    max_budget_usd = 0

    def iter_tasks(self, count: int, selection: str, *, dry_run: bool) -> list[TaskDescriptor]:
        if not dry_run:
            raise NotImplementedError(f"{self.name}: real task selection needs {self.real_infra}")
        if count < 0:
            raise ValueError("count must be non-negative")
        if not selection:
            raise ValueError("selection must be non-empty")
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
        del repo_root
        if not dry_run:
            raise NotImplementedError(f"{self.name}: real task execution needs {self.real_infra}")

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


def _fingerprint(value: str) -> int:
    return sum((index + 1) * ord(char) for index, char in enumerate(value))
