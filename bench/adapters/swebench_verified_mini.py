from __future__ import annotations

from .base import Adapter


class SWEBenchVerifiedMiniAdapter(Adapter):
    """Adapter for a local SWE-bench Verified Mini task subset.

    Expected dataset layout:
      $SWEBENCH_VERIFIED_MINI_DIR/instances.jsonl
      $SWEBENCH_VERIFIED_MINI_DIR/instances.json
      $SWEBENCH_VERIFIED_MINI_DIR/tasks.jsonl
      $SWEBENCH_VERIFIED_MINI_DIR/tasks.json

    Each instance needs an id/instance_id, problem_statement/prompt, and either
    acceptance.command/grader_command or SWEBENCH_VERIFIED_MINI_GRADER_CMD.
    """

    name = "swebench_verified_mini"
    display_name = "SWE-bench Verified Mini"
    real_infra = "SWE-bench Verified Mini dataset and Docker SWE-bench harness"
    dry_run_focus = "SWE-bench Verified Mini instance"
    max_budget_usd = 8
    dataset_env_var = "SWEBENCH_VERIFIED_MINI_DIR"
    dataset_default = "bench/datasets/swebench_verified_mini"
    dataset_layout = "instances.jsonl, instances.json, tasks.jsonl, or tasks.json at the dataset root"
    issue_ref = "#2"
    task_file_candidates = ("instances.jsonl", "instances.json", "tasks.jsonl", "tasks.json")
    grader_command_env_var = "SWEBENCH_VERIFIED_MINI_GRADER_CMD"
    grader_infra = "Docker-enabled SWE-bench evaluator with the Verified Mini subset"
