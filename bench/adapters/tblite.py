from __future__ import annotations

from .base import Adapter


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
