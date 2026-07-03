from __future__ import annotations

from .base import Adapter
from .rexbench import RExBenchAdapter
from .swebench_pro_public import SWEBenchProPublicAdapter
from .swebench_verified_mini import SWEBenchVerifiedMiniAdapter
from .terminalbench_2_1 import TerminalBench21Adapter
from .tblite import TBLiteAdapter


ADAPTERS: dict[str, Adapter] = {
    adapter.name: adapter
    for adapter in (
        RExBenchAdapter(),
        TBLiteAdapter(),
        SWEBenchVerifiedMiniAdapter(),
        TerminalBench21Adapter(),
        SWEBenchProPublicAdapter(),
    )
}


def get_adapter(name: str) -> Adapter:
    try:
        return ADAPTERS[name]
    except KeyError as exc:
        available = ", ".join(sorted(ADAPTERS))
        raise KeyError(f"unknown benchmark adapter {name!r}; available: {available}") from exc
