from __future__ import annotations

from .base import Adapter


class TBLiteAdapter(Adapter):
    name = "tblite"
    display_name = "OpenThoughts-TBLite"
    real_infra = "OpenThoughts-TBLite dataset and Harbor"
    dry_run_focus = "Terminal-Bench task"
