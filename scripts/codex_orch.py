#!/usr/bin/env python3
"""Ledger / orchestration CLI entry point for the codex-orchestrator plugin.

The real implementation lives in the ``codex_orchestrator`` package. This thin
module exists because it is invoked BY PATH from the plugin skills
(``${CLAUDE_PLUGIN_ROOT}/scripts/codex_orch.py``) and ``bin/codex-orch`` — a
path invocation is PYTHONPATH-free and robust inside the plugin container, so it
must stay a file here. It re-exports the package API and dispatches to
``codex_orchestrator.cli.main``.
"""
from __future__ import annotations

from codex_orchestrator.benchmark import *
from codex_orchestrator.claims import *
from codex_orchestrator.cli import *
from codex_orchestrator.contract import *
from codex_orchestrator.events import *
from codex_orchestrator.gate import *
from codex_orchestrator.ledger import *
from codex_orchestrator.prompts import *
from codex_orchestrator.runmeta import *
from codex_orchestrator.scoring import *
from codex_orchestrator.store import *


if __name__ == "__main__":
    raise SystemExit(main())
