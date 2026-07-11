from __future__ import annotations

import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
JOURNAL_ENTRY_TYPES = {
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

        self.assertIn("## Workflow\n", readme)
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

    def test_run_journal_is_claude_authored_not_global_evidence(self) -> None:
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
        contract = (ROOT / "docs" / "orchestration-contract.md").read_text(encoding="utf-8")

        self.assertIn("small omission check", contract)
        self.assertIn("does not enforce every documented field", contract)

    def test_claude_verification_and_independent_review_use_different_context(self) -> None:
        review = " ".join(
            (ROOT / "skills/orchestrate/references/review.md")
            .read_text(encoding="utf-8")
            .casefold()
            .split()
        )
        workflow = " ".join(
            (ROOT / "skills/workflow/SKILL.md").read_text(encoding="utf-8").casefold().split()
        )

        self.assertIn("claude's own verification", review)
        self.assertIn("read an agent handoff first", review)
        self.assertIn("fresh named `codex-review-nn` agent", review)
        self.assertIn("never resume the implementation session", review)
        for excluded in (
            "implementer handoff",
            "claimed test results",
            "earlier review verdicts",
            "claude's tentative conclusion",
        ):
            self.assertIn(excluded, review)
        self.assertIn("must not relay", review)
        self.assertIn("first-pass prompt", review)
        self.assertIn("initial independent review", workflow)
        self.assertIn("starts a fresh agent and native session", workflow)

    def test_review_target_is_immutable_or_has_a_scoped_reservation(self) -> None:
        review = " ".join(
            (ROOT / "skills/orchestrate/references/review.md")
            .read_text(encoding="utf-8")
            .casefold()
            .split()
        )
        compute = " ".join(
            (ROOT / "skills/orchestrate/references/compute.md")
            .read_text(encoding="utf-8")
            .casefold()
            .split()
        )

        self.assertIn("--commit <sha>", review)
        self.assertIn("immutable", review)
        self.assertIn("no source-file write reservation", review)
        self.assertIn("record the base head sha", review)
        self.assertIn("independent `--uncommitted` review reserves", compute)
        self.assertIn("task's declared `files`", compute)
        self.assertIn("execution terminates", compute)
        self.assertIn("terminal blocked/failed outcome", compute)
        self.assertIn("disjoint work may continue", compute)
        self.assertIn("separate worktree or commit a stable snapshot", compute)

    def test_consensus_distinguishes_context_from_family_diversity(self) -> None:
        consensus = " ".join(
            (ROOT / "skills/orchestrate/references/consensus.md")
            .read_text(encoding="utf-8")
            .casefold()
            .split()
        )
        report = " ".join(
            (ROOT / "skills/report/SKILL.md").read_text(encoding="utf-8").casefold().split()
        )

        self.assertIn("anthropic claude family in claude code", consensus)
        self.assertIn("openai codex/gpt family in codex", consensus)
        self.assertIn("does not add model-family diversity", consensus)
        self.assertIn("agent count is never a decision rule", consensus)
        for criterion in ("acceptance fit", "direct evidence", "reversibility"):
            self.assertIn(criterion, consensus)
        self.assertIn("fresh codex review as context-independent", report)
        self.assertIn("recorded claude-codex participation", report)

    def test_review_effort_is_risk_scaled_and_lens_diverse(self) -> None:
        review = " ".join(
            (ROOT / "skills/orchestrate/references/review.md")
            .read_text(encoding="utf-8")
            .casefold()
            .split()
        )
        workflow = " ".join(
            (ROOT / "skills/workflow/SKILL.md").read_text(encoding="utf-8").casefold().split()
        )

        self.assertIn("one primary review lens", review)
        self.assertIn("distinct unresolved question", review)
        self.assertIn("routine bounded work", workflow)
        self.assertIn("codex implementation plus claude verification", workflow)
        self.assertIn("material localized risk", workflow)
        self.assertIn("unanchored alternative", workflow)

    def test_only_jsonl_fences_mark_journal_examples(self) -> None:
        sample = """```json
not valid JSON and intentionally ignored
```
```jsonl
{"type":"task"}
```"""

        self.assertEqual(jsonl_blocks(sample), [[(5, '{"type":"task"}')]])

    def test_documented_journal_examples_are_one_entry_per_line(self) -> None:
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
                        f"{relative_path}:{line_number}: journal entry must be an object",
                    )
                    self.assertIn(
                        event.get("type"),
                        JOURNAL_ENTRY_TYPES,
                        f"{relative_path}:{line_number}: undocumented journal entry type",
                    )
        self.assertGreater(examples, 0, "documentation must contain a marked journal example")


if __name__ == "__main__":
    unittest.main()
