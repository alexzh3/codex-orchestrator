from __future__ import annotations

from pathlib import Path

from .base import Adapter
from .base import TaskDescriptor


class SWEBenchProPublicAdapter(Adapter):
    name = "swebench_pro_public"
    display_name = "SWE-bench Pro (public)"
    real_infra = "SWE-bench Pro Docker evaluator + jefzda/sweap-images (adapter not yet implemented)"
    dry_run_focus = "SWE-bench Pro public instance"
    max_budget_usd = 5
    dataset_env_var = "SWEBENCH_PRO_DIR"
    dataset_default = "bench/datasets/swebench_pro_public"
    dataset_layout = "SWE-bench Pro public task descriptors at the dataset root"
    issue_ref = "#18"

    def resolve_frozen_tasks(self, entries: list[dict[str, object]], *, dry_run: bool) -> list[TaskDescriptor]:
        if dry_run:
            return super().resolve_frozen_tasks(entries, dry_run=dry_run)
        raise RuntimeError(
            f"{self.display_name} real frozen runs are adapter_pending ({self.issue_ref}); "
            f"the SWE-bench Pro public adapter is not yet implemented. Required infra: {self.real_infra}."
        )

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
            f"{self.display_name} real runs are adapter_pending ({self.issue_ref}); "
            f"the SWE-bench Pro public adapter is not yet implemented. Required infra: {self.real_infra}."
        )
