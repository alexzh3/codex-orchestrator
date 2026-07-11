#!/usr/bin/env python3
"""Run-journal validation and Codex agent monitoring tools.

Invoked by path from the plugin skills, so this stable entry point remains in
``scripts/``. Command coordination lives in ``codex_orchestrator.cli``.
"""

from __future__ import annotations

from codex_orchestrator.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
