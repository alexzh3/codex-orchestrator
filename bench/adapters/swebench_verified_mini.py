from __future__ import annotations

from .base import Adapter


class SWEBenchVerifiedMiniAdapter(Adapter):
    name = "swebench_verified_mini"
    display_name = "SWE-bench Verified Mini"
    real_infra = "SWE-bench Verified Mini dataset and Docker SWE-bench harness"
    dry_run_focus = "SWE-bench Verified Mini instance"
