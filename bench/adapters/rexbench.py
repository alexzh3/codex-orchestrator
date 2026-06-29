from __future__ import annotations

from .base import Adapter


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
    real_infra = "RExBench dataset and executor"
    dry_run_focus = "research-experiment implementation task"
    max_budget_usd = 5
    dataset_env_var = "REXBENCH_DIR"
    dataset_default = "bench/datasets/rexbench"
    dataset_layout = "tasks.jsonl or tasks.json at the dataset root, with task objects"
    issue_ref = "#10"
    task_file_candidates = ("tasks.jsonl", "tasks.json", "rexbench.jsonl", "rexbench.json")
    grader_command_env_var = "REXBENCH_GRADER_CMD"
    grader_infra = "RExBench executor and grader"
