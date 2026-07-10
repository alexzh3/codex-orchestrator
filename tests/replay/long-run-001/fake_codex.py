#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

IMPLEMENTATION_HANDOFF = """## Status

complete

## Summary

Implemented the scoped example feature.

## Files Changed

- `src/example.py`

## Claims / Findings

- The new behavior is covered by focused tests.

## Commands Reported

- `python3 -m unittest tests.test_example` — passed

## Caveats / Blockers

- None.
"""

REVIEW_HANDOFF = """## Status

complete

## Summary

Reviewed the implementation and added focused coverage.

## Files Changed

- `tests/test_example.py`

## Claims / Findings

- The implementation matches the assignment.
- No blocking issue remains.

## Commands Reported

- `python3 -m unittest tests.test_example` — passed

## Caveats / Blockers

- None.
"""


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Local Codex stand-in for execution fixtures.")
    parser.add_argument("command", choices=("exec",))
    parser.add_argument("--json", action="store_true", dest="emit_json")
    parser.add_argument("--output-last-message", required=True, type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if not args.emit_json:
        raise SystemExit("fake codex requires --json")

    prompt = sys.stdin.read()
    is_review = "# Review assignment" in prompt
    handoff = REVIEW_HANDOFF if is_review else IMPLEMENTATION_HANDOFF
    thread_id = "fixture-review" if is_review else "fixture-impl"

    args.output_last_message.parent.mkdir(parents=True, exist_ok=True)
    args.output_last_message.write_text(handoff, encoding="utf-8")

    events = [
        {"type": "thread.started", "thread_id": thread_id},
        {"type": "turn.started", "thread_id": thread_id, "turn_id": "turn-1"},
        {
            "type": "item.completed",
            "item": {"type": "agent_message", "text": handoff.rstrip()},
        },
        {
            "type": "turn.completed",
            "thread_id": thread_id,
            "turn_id": "turn-1",
            "usage": {"input_tokens": 100 if is_review else 80, "output_tokens": 40},
        },
    ]
    for event in events:
        print(json.dumps(event, separators=(",", ":")), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
