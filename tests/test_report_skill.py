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
    def test_skill_authors_complete_report_after_gate_and_doctor(self) -> None:
        skill = REPORT_SKILL.read_text(encoding="utf-8")

        self.assertIn(REPORT_TEMPLATE, skill)
        self.assertNotIn('codex_orch.py" report', skill)
        self.assertIn("### Gate Result", skill)
        self.assertIn("### Risks / Follow-ups", skill)
        self.assertLess(skill.index("`gate`"), skill.index(REPORT_TEMPLATE))
        self.assertLess(skill.index("`doctor`"), skill.index(REPORT_TEMPLATE))


if __name__ == "__main__":
    unittest.main()
