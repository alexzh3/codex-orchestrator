from __future__ import annotations

from .base import Adapter


class RExBenchAdapter(Adapter):
    name = "rexbench"
    display_name = "RExBench"
    real_infra = "RExBench dataset and executor"
    dry_run_focus = "research-experiment implementation task"
