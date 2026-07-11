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
    def test_workflow_skill_owns_the_exact_close_sequence(self) -> None:
        phrase = "validate → run_closed → report.md"
        owners = [
            path.relative_to(ROOT).as_posix()
            for path in documentation_paths()
            if phrase in path.read_text(encoding="utf-8")
        ]

        self.assertEqual(owners, ["skills/workflow/SKILL.md"])

    def test_readme_diagrams_the_full_workflow(self) -> None:
        readme = (ROOT / "README.md").read_text(encoding="utf-8")

        self.assertIn("## Full Workflow", readme)
        self.assertIn("```mermaid\nflowchart TD", readme)
        for step in (
            "Codex reviews the plan when useful",
            "Claude assigns scoped work",
            "Codex implements or reviews",
            "Claude verifies the result",
            "issues found",
            "Codex fixes",
            "final judgment",
            "final report",
        ):
            self.assertIn(step, readme)
        self.assertIn("F --> E", readme)

    def test_ledger_is_a_claude_authored_journal_not_global_evidence(self) -> None:
        contract = "\n".join(
            (ROOT / path).read_text(encoding="utf-8").casefold()
            for path in (
                "README.md",
                "skills/orchestrate/SKILL.md",
                "skills/report/SKILL.md",
            )
        )

        self.assertIn("append-only orchestration journal", contract)
        self.assertIn("not independent evidence", contract)
        self.assertNotIn("primary run record", contract)
        self.assertNotIn("source of truth", contract)

    def test_validation_is_documented_as_an_omission_check_not_a_schema(self) -> None:
        contract = (ROOT / "docs" / "consensus-and-reviews.md").read_text(encoding="utf-8")

        self.assertIn("small omission check", contract)
        self.assertIn("does not enforce every documented field", contract)

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
