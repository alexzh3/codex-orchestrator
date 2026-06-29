from __future__ import annotations

import unittest
from pathlib import Path

from bench.runners.run_replay import run_case


ROOT = Path(__file__).resolve().parents[1]
CASE_DIR = ROOT / "bench" / "cases" / "replay" / "long-run-001"


class LongWorkflowReportTests(unittest.TestCase):
    def report_section(self, report: str, heading: str) -> str:
        return report.split(heading, 1)[1].split("\n## ", 1)[0]

    def test_replay_fixture_matches_golden_and_surfaces_review_risks(self) -> None:
        result = run_case(CASE_DIR)

        self.assertTrue(result.golden_match)
        self.assertTrue(result.payload["passed"])
        self.assertGreaterEqual(result.payload["report_score"], 0.95)
        self.assertLessEqual(result.payload["report_score"], 1.0)

        risks_section = self.report_section(result.generated_report, "## Risks / Follow-ups")
        consensus_section = self.report_section(result.generated_report, "## Consensus")

        self.assertIn(
            "- Test (failed): Replay smoke test failed on stale parser warning assertion",
            risks_section,
        )
        self.assertIn("- Session codex-ide-review has low parser confidence.", risks_section)
        self.assertIn("### Reviews", consensus_section)
        self.assertIn("- **Manual / agent review** (passed)", consensus_section)
        self.assertIn(
            "Final Codex review passed with the failed verification documented",
            consensus_section,
        )


if __name__ == "__main__":
    unittest.main()
