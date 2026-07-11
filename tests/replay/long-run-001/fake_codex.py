#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

CHECK_COMMAND = [
    sys.executable,
    "-m",
    "unittest",
    "discover",
    "-s",
    "tests",
    "-p",
    "test_example.py",
    "-q",
]

IMPLEMENTATION_HANDOFF = """## Status

complete

## Summary

Implemented the scoped example feature.

## Files Changed

- `src/example.py`
- `tests/test_example.py`

## Claims / Findings

- The new behavior is covered by focused tests.

## Commands Reported

- `python3 -m unittest discover -s tests -p test_example.py -q` — passed

## Caveats / Blockers

- None.
"""

REVIEW_HANDOFF = """## Status

complete

## Summary

Reviewed the stable implementation target without editing it.

## Files Changed

- None.

## Claims / Findings

- The implementation matches the assignment.
- No blocking issue remains.

## Commands Reported

- `python3 -m unittest discover -s tests -p test_example.py -q` — passed

## Caveats / Blockers

- None.
"""

EXAMPLE_MODULE = """def double(value: int) -> int:
    return value * 2
"""

EXAMPLE_TEST = """import unittest

from src.example import double


class ExampleTests(unittest.TestCase):
    def test_positive_value(self) -> None:
        self.assertEqual(double(3), 6)

    def test_zero(self) -> None:
        self.assertEqual(double(0), 0)


if __name__ == "__main__":
    unittest.main()
"""


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Local Codex stand-in for execution fixtures.")
    parser.add_argument("command", choices=("exec",))
    parser.add_argument("--json", action="store_true", dest="emit_json")
    parser.add_argument("--output-last-message", required=True, type=Path)
    return parser


def prepare_target(is_review: bool) -> None:
    source = Path("src/example.py")
    test = Path("tests/test_example.py")
    if is_review:
        if not source.is_file() or not test.is_file():
            raise SystemExit("review target is not ready")
    else:
        source.parent.mkdir(parents=True, exist_ok=True)
        test.parent.mkdir(parents=True, exist_ok=True)
        source.write_text(EXAMPLE_MODULE, encoding="utf-8")
        test.write_text(EXAMPLE_TEST, encoding="utf-8")

    check = subprocess.run(CHECK_COMMAND, check=False, text=True, capture_output=True)
    if check.returncode != 0:
        raise SystemExit(check.stdout + check.stderr)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if not args.emit_json:
        raise SystemExit("fake codex requires --json")

    prompt = sys.stdin.read()
    is_review = "# Review assignment" in prompt
    prepare_target(is_review)
    handoff = REVIEW_HANDOFF if is_review else IMPLEMENTATION_HANDOFF
    thread_id = "fixture-review" if is_review else "fixture-impl"

    args.output_last_message.parent.mkdir(parents=True, exist_ok=True)
    args.output_last_message.write_text(handoff, encoding="utf-8")

    events = [
        {"type": "thread.started", "thread_id": thread_id},
        {"type": "turn.started"},
        {
            "type": "item.completed",
            "item": {"type": "agent_message", "text": handoff.rstrip()},
        },
        {
            "type": "turn.completed",
            "usage": {"input_tokens": 100 if is_review else 80, "output_tokens": 40},
        },
    ]
    for event in events:
        print(json.dumps(event, separators=(",", ":")), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
