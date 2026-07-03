from __future__ import annotations

from pathlib import Path

from .base import Adapter
from .base import TaskDescriptor


class RExBenchAdapter(Adapter):
    """Adapter for a local RExBench checkout.

    Expected dataset layout:
      $REXBENCH_DIR/tasks.jsonl
      $REXBENCH_DIR/tasks.json
      $REXBENCH_DIR/rexbench.jsonl
      $REXBENCH_DIR/rexbench.json

    Each task record needs an id/task_id, prompt/instructions/description, and
    either acceptance.command/grader_command or REXBENCH_GRADER_CMD.
    """

    name = "rexbench"
    display_name = "RExBench"
    real_infra = (
        "RExBench external submission workflow: submit patch ZIPs via rexbench.com "
        "for async email/leaderboard grading; no local pass/fail grader exists or is possible. "
        "Local GPU execution is additionally blocked because the env pins torch <=2.6, "
        "which is incompatible with sm_120."
    )
    dry_run_focus = "research-experiment implementation task"
    max_budget_usd = 5
    dataset_env_var = "REXBENCH_DIR"
    dataset_default = "bench/datasets/rexbench"
    dataset_layout = "tasks.jsonl or tasks.json at the dataset root, with task objects"
    issue_ref = "#10"
    task_file_candidates = ("tasks.jsonl", "tasks.json", "rexbench.jsonl", "rexbench.json")
    grader_command_env_var = "REXBENCH_GRADER_CMD"
    grader_infra = "RExBench private async grading via rexbench.com patch ZIP submission"

    def run_task(
        self,
        task: TaskDescriptor,
        plugin_ref: str,
        *,
        dry_run: bool,
        repo_root: Path,
        work_dir: Path,
    ) -> dict[str, object]:
        if dry_run:
            return super().run_task(
                task,
                plugin_ref,
                dry_run=dry_run,
                repo_root=repo_root,
                work_dir=work_dir,
            )
        raise RuntimeError(
            f"{self.display_name} real runs require the external submission workflow ({self.issue_ref}): "
            "submit patch ZIPs via rexbench.com for async email/leaderboard grading. "
            "There is no local pass/fail grader and none is possible; local GPU execution is "
            "also blocked because the environment pins torch <=2.6, incompatible with sm_120."
        )
