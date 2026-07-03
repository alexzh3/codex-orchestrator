#!/usr/bin/env python3
"""Codex JSONL session-log parser CLI for the plugin's monitoring helpers.

Invoked BY PATH (``${CLAUDE_PLUGIN_ROOT}/scripts/codex_orch_parse.py``) from the
orchestrate skill's monitoring flow, so it must stay a file here. The real logic
lives in ``codex_orchestrator.parse``.
"""
from __future__ import annotations

from codex_orchestrator.parse import *

if __name__ == "__main__":
    raise SystemExit(main())
