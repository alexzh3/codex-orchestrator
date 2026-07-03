from __future__ import annotations

import os
import subprocess
from pathlib import Path

from bench.runners.run_claude import empty_token_usage
from bench.runners.run_claude import plugin_ref_dir
from codex_orch import validate_benchmark_result

from .base import Adapter
from .base import TaskDescriptor


class TBLiteAdapter(Adapter):
    """Adapter for a local OpenThoughts-TBLite/Terminal-Bench checkout.

    Expected dataset layout:
      $TBLITE_DIR/tasks.jsonl
      $TBLITE_DIR/tasks.json
      $TBLITE_DIR/tblite.jsonl
      $TBLITE_DIR/tblite.json

    Each task record needs an id/task_id, prompt/instructions/description, and
    either acceptance.command/grader_command or TBLITE_GRADER_CMD.
    """

    name = "tblite"
    display_name = "OpenThoughts-TBLite"
    real_infra = "OpenThoughts-TBLite dataset and Harbor"
    dry_run_focus = "Terminal-Bench task"
    max_budget_usd = 5
    dataset_env_var = "TBLITE_DIR"
    dataset_default = "bench/datasets/tblite"
    dataset_layout = "tasks.jsonl or tasks.json at the dataset root, with task objects"
    issue_ref = "#3"
    task_file_candidates = ("tasks.jsonl", "tasks.json", "tblite.jsonl", "tblite.json")
    grader_command_env_var = "TBLITE_GRADER_CMD"
    grader_infra = "Harbor with the OpenThoughts-TBLite tasks and grader"
    harbor_dataset_env_var = "TBLITE_HARBOR_DATASET"
    harbor_dataset_default = "openthoughts-tblite"
    harbor_oauth_token_env = "CLAUDE_CODE_OAUTH_TOKEN"
    harbor_model = "claude-opus-4-8"
    harbor_effort = "max"

    def run_task(
        self,
        task: TaskDescriptor,
        plugin_ref: str,
        *,
        dry_run: bool,
        repo_root: Path,
        work_dir: Path,
    ) -> dict[str, object]:
        if dry_run or self._has_patched_base_runner_hooks():
            return super().run_task(
                task,
                plugin_ref,
                dry_run=dry_run,
                repo_root=repo_root,
                work_dir=work_dir,
            )

        from bench.harbor_runner import run_tblite_task_via_harbor

        task_id = _string_field(task, "id")
        timeout = _non_negative_int(task.get("timeout_seconds"), self.default_timeout_seconds)
        dataset = os.environ.get(self.harbor_dataset_env_var, self.harbor_dataset_default)
        try:
            plugin_dir, remove_plugin_worktree = _materialize_plugin_ref(
                plugin_ref,
                repo_root=repo_root,
                work_dir=work_dir,
            )
        except RuntimeError as exc:
            raise RuntimeError(
                f"{self.display_name} real run could not materialize plugin_ref "
                f"{plugin_ref!r}; required infra: {self.real_infra}; detail: {exc}"
            ) from exc
        try:
            harbor_result = run_tblite_task_via_harbor(
                task_id,
                plugin_dir,
                dataset=dataset,
                model=self.harbor_model,
                effort=self.harbor_effort,
                jobs_dir=work_dir / "harbor-jobs",
                oauth_token_env=self.harbor_oauth_token_env,
                timeout=timeout,
            )
        finally:
            if remove_plugin_worktree:
                _remove_plugin_worktree(repo_root, plugin_dir)

        token_usage = harbor_result.get("tokens")
        if not isinstance(token_usage, dict):
            token_usage = empty_token_usage()
        claude_tokens = harbor_result.get("claude_tokens")
        if not isinstance(claude_tokens, dict):
            claude_tokens = token_usage
        gpt_tokens = harbor_result.get("gpt_tokens")
        if not isinstance(gpt_tokens, dict):
            gpt_tokens = None
        combined_tokens = harbor_result.get("combined_tokens")
        if not isinstance(combined_tokens, dict):
            combined_tokens = None

        external_score = {
            "benchmark": self.name,
            "task_id": task_id,
            "required_infra": self.real_infra,
            "harbor_dataset": dataset,
            "resolved": harbor_result.get("resolved"),
            "verifier_exit": harbor_result.get("verifier_exit"),
            "score": harbor_result.get("score"),
            "verifier_rewards": harbor_result.get("verifier_rewards"),
            "raw_result_path": harbor_result.get("raw_result_path"),
            "token_usage": token_usage,
            "token_breakdown": {
                "claude": _claude_token_breakdown(claude_tokens),
                "gpt": _gpt_token_breakdown(gpt_tokens),
                "combined": _combined_token_breakdown(combined_tokens),
            },
            "exception": harbor_result.get("exception"),
            "codex_sessions_spawned": harbor_result.get("codex_sessions_spawned"),
            "real_orchestration": harbor_result.get("real_orchestration"),
            "orchestration_note": harbor_result.get("orchestration_note"),
        }
        token_note = harbor_result.get("token_note")
        if isinstance(token_note, str) and token_note:
            external_score["token_note"] = token_note
        if harbor_result.get("real_orchestration") is False:
            external_score["degenerate_no_codex"] = True
        codex_sessions_spawned = _non_negative_int(
            harbor_result.get("codex_sessions_spawned"),
            0,
        )
        payload: dict[str, object] = {
            "suite": self.name,
            "case_id": task_id,
            "plugin_ref": plugin_ref,
            "repo_commit": None,
            "passed": harbor_result.get("resolved") is True,
            "wall_seconds": _non_negative_number(harbor_result.get("wall_seconds"), 0.0),
            "claude_turns": None,
            "codex_sessions": codex_sessions_spawned,
            "codex_reviews": 0,
            "manual_interventions": None,
            "prompt_log_pairs_complete": False,
            "ledger_errors": 0,
            "gate_passed": None,
            "report_score": 0.0,
            "token_usage": token_usage,
            "external_score": external_score,
        }
        validate_benchmark_result(payload)
        return payload

    def _has_patched_base_runner_hooks(self) -> bool:
        return "_run_claude_case" in self.__dict__ or "_grade" in self.__dict__


def _string_field(payload: dict[str, object], field: str) -> str:
    value = payload.get(field)
    if not isinstance(value, str) or not value:
        raise ValueError(f"task is missing non-empty string field {field}")
    return value


def _non_negative_int(value: object, default: int) -> int:
    return value if type(value) is int and value >= 0 else default


def _non_negative_number(value: object, default: float) -> float:
    if isinstance(value, bool):
        return default
    if isinstance(value, (int, float)) and value >= 0:
        return float(value)
    return default


def _token_int(payload: dict[str, object] | None, field: str) -> int | None:
    if not isinstance(payload, dict):
        return None
    value = payload.get(field)
    return value if type(value) is int and value >= 0 else None


def _token_cost(payload: dict[str, object] | None) -> float | None:
    if not isinstance(payload, dict):
        return None
    value = payload.get("cost_usd")
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)) and value >= 0:
        return float(value)
    return None


def _claude_token_breakdown(tokens: dict[str, object] | None) -> dict[str, object]:
    return {
        "input_tokens": _token_int(tokens, "input_tokens"),
        "output_tokens": _token_int(tokens, "output_tokens"),
        "total_tokens": _token_int(tokens, "total_tokens"),
        "cost_usd": _token_cost(tokens),
    }


def _gpt_token_breakdown(tokens: dict[str, object] | None) -> dict[str, object]:
    return {
        "input_tokens": _token_int(tokens, "input_tokens"),
        "output_tokens": _token_int(tokens, "output_tokens"),
        "total_tokens": _token_int(tokens, "total_tokens"),
        "num_sessions": _token_int(tokens, "num_sessions"),
        "cost_usd": _token_cost(tokens),
    }


def _combined_token_breakdown(tokens: dict[str, object] | None) -> dict[str, object]:
    return {
        "input_tokens": _token_int(tokens, "input_tokens"),
        "output_tokens": _token_int(tokens, "output_tokens"),
        "total_tokens": _token_int(tokens, "total_tokens"),
    }


def _materialize_plugin_ref(
    plugin_ref: str,
    *,
    repo_root: Path,
    work_dir: Path,
) -> tuple[Path, bool]:
    plugin_dir = plugin_ref_dir(plugin_ref, work_dir)
    if plugin_dir.is_dir():
        return plugin_dir, False

    candidate = Path(plugin_ref).expanduser()
    if candidate.is_absolute() or candidate.exists():
        resolved = candidate.resolve()
        if not resolved.is_dir():
            raise RuntimeError(f"plugin_ref path is not a directory: {resolved}")
        return resolved, False

    plugin_dir.parent.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        [
            "git",
            "-C",
            str(repo_root),
            "worktree",
            "add",
            "--detach",
            str(plugin_dir),
            plugin_ref,
        ],
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or f"exit {result.returncode}"
        raise RuntimeError(f"could not materialize plugin_ref {plugin_ref!r}: {detail}")
    return plugin_dir, True


def _remove_plugin_worktree(repo_root: Path, plugin_dir: Path) -> None:
    subprocess.run(
        ["git", "-C", str(repo_root), "worktree", "remove", "--force", str(plugin_dir)],
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
