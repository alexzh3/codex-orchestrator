from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPORT_SKILL = ROOT / "skills" / "report" / "SKILL.md"

REPORT_TEMPLATE = """# Report

## Summary

## Changes

## Orchestration Graph

## Consensus

## Final Results"""


class ReportSkillTests(unittest.TestCase):
    def test_skill_authors_complete_report_with_exact_section_order(self) -> None:
        skill = REPORT_SKILL.read_text(encoding="utf-8")

        self.assertIn(REPORT_TEMPLATE, skill)
        self.assertIn("### Gate Result", skill)
        self.assertIn("### Risks / Follow-ups", skill)
        self.assertIn("Mermaid `flowchart TD`", skill)
        self.assertIn('A_CLAUDE{{"Claude Code<br/>planner · orchestrator"}}', skill)
        self.assertIn("Show only evidence that affected", skill)
        self.assertIn("one node per named agent", skill)

    def test_skill_requires_a_closed_and_validated_run(self) -> None:
        skill = REPORT_SKILL.read_text(encoding="utf-8")
        normalized = " ".join(skill.lower().split())

        self.assertIn(
            "`run_closed.validation` contains the complete descriptive validation", normalized
        )
        self.assertIn("`run_closed` is the final journal entry", normalized)
        self.assertIn("no further run work is planned", normalized)
        self.assertNotIn("validate → run_closed → report.md", normalized)

    def test_skill_uses_claim_specific_sources_and_creates_one_final_report(self) -> None:
        skill = " ".join(REPORT_SKILL.read_text(encoding="utf-8").lower().split())

        self.assertIn("actual delivery: final repository state relative to", skill)
        self.assertIn(
            "compare the final repository state with `run_started.repo_head` and "
            "`run_started.repo_status`",
            skill,
        )
        self.assertIn("do not attribute initially dirty paths without supporting evidence", skill)
        self.assertIn("agent claims: exact handoffs", skill)
        self.assertIn("not independent evidence", skill)
        self.assertIn("create the final `report.md` once", skill)

    def test_skill_reconciles_numeric_totals_and_keeps_linear_graphs_small(self) -> None:
        skill = " ".join(REPORT_SKILL.read_text(encoding="utf-8").lower().split())

        self.assertIn("keep a linear run minimal", skill)
        self.assertIn("reconcile every numeric total", skill)

if __name__ == "__main__":
    unittest.main()
