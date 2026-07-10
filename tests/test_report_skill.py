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
        headings = [
            line
            for line in REPORT_TEMPLATE.splitlines()
            if line.startswith("## ")
        ]
        template_start = skill.index(REPORT_TEMPLATE)
        template = skill[template_start : template_start + len(REPORT_TEMPLATE)]
        self.assertEqual(
            [line for line in template.splitlines() if line.startswith("## ")],
            headings,
        )

    def test_skill_closes_run_between_validation_and_report(self) -> None:
        skill = REPORT_SKILL.read_text(encoding="utf-8")
        normalized = " ".join(skill.lower().split())

        self.assertRegex(normalized, r"validate\s*(?:->|→)\s*run_closed\s*(?:->|→)\s*report\.md")
        self.assertIn("judgment", normalized)

    def test_skill_uses_claim_specific_sources_and_creates_one_final_report(self) -> None:
        skill = " ".join(REPORT_SKILL.read_text(encoding="utf-8").lower().split())

        self.assertIn("actual delivery: final repository state and diff", skill)
        self.assertIn("agent claims: exact handoffs", skill)
        self.assertIn("not independent evidence", skill)
        self.assertIn("create the final `report.md` once", skill)

    def test_skill_has_no_legacy_report_protocol_dependency(self) -> None:
        skill = REPORT_SKILL.read_text(encoding="utf-8")
        retired_event = "gate" + "_result"
        retired_cli = "codex_" + "orch.py"

        self.assertNotIn(f'"type": "{retired_event}"', skill)
        self.assertNotIn(f"latest `{retired_event}`", skill)
        self.assertNotIn(f'{retired_cli}" report', skill)


if __name__ == "__main__":
    unittest.main()
