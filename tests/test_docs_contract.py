from __future__ import annotations

import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LEDGER_EVENT_TYPES = {
    "run_started",
    "task",
    "execution",
    "execution_result",
    "verification",
    "decision",
    "run_closed",
}


def documentation_paths() -> list[Path]:
    paths = [ROOT / "README.md"]
    for directory in ("commands", "docs", "skills"):
        paths.extend((ROOT / directory).rglob("*.md"))
    return sorted(path for path in paths if path.is_file())


def contract_source_paths() -> list[Path]:
    paths = [ROOT / "README.md"]
    for directory in ("bin", "commands", "docs", "scripts", "skills", "tests"):
        paths.extend(path for path in (ROOT / directory).rglob("*") if path.is_file())
    return sorted(
        path for path in paths if path.suffix in {"", ".jsonl", ".md", ".py"}
    )


def jsonl_blocks(text: str) -> list[list[tuple[int, str]]]:
    blocks: list[list[tuple[int, str]]] = []
    current: list[tuple[int, str]] | None = None
    for line_number, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        if current is None:
            if stripped == "```jsonl":
                current = []
            continue
        if stripped == "```":
            blocks.append(current)
            current = None
            continue
        current.append((line_number, line))
    if current is not None:
        raise AssertionError("unclosed ```jsonl block")
    return blocks


class DocumentationContractTests(unittest.TestCase):
    def test_execution_vocabulary_has_no_retired_custom_terms(self) -> None:
        retired_terms = (
            "dis" + "patch",
            "check" + "point",
            "doc" + "tor",
            "work" + "er",
        )
        for path in contract_source_paths():
            relative_path = path.relative_to(ROOT)
            text = path.read_text(encoding="utf-8").casefold()
            for term in retired_terms:
                self.assertNotIn(term, relative_path.as_posix().casefold(), relative_path)
                self.assertNotIn(term, text, relative_path)

    def test_only_jsonl_fences_mark_ledger_examples(self) -> None:
        sample = """```json
not valid JSON and intentionally ignored
```
```jsonl
{"type":"task"}
```"""

        self.assertEqual(jsonl_blocks(sample), [[(5, '{"type":"task"}')]])

    def test_documented_ledger_examples_are_one_event_per_line(self) -> None:
        examples = 0
        for path in documentation_paths():
            relative_path = path.relative_to(ROOT)
            try:
                blocks = jsonl_blocks(path.read_text(encoding="utf-8"))
            except AssertionError as error:
                self.fail(f"{relative_path}: {error}")
            for block in blocks:
                for line_number, line in block:
                    if not line.strip():
                        continue
                    examples += 1
                    try:
                        event = json.loads(line)
                    except json.JSONDecodeError as error:
                        self.fail(f"{relative_path}:{line_number}: {error}")
                    self.assertIsInstance(
                        event,
                        dict,
                        f"{relative_path}:{line_number}: ledger event must be an object",
                    )
                    self.assertIn(
                        event.get("type"),
                        LEDGER_EVENT_TYPES,
                        f"{relative_path}:{line_number}: undocumented ledger event type",
                    )
        self.assertGreater(examples, 0, "documentation must contain a marked ledger example")


if __name__ == "__main__":
    unittest.main()
