from __future__ import annotations

import json
import unittest
from pathlib import Path

from bench.runners.run_replay import run_case
from codex_orch_report import report_completeness_score


ROOT = Path(__file__).resolve().parents[1]
CASE_DIR = ROOT / "bench" / "cases" / "replay" / "long-run-001"


class LongWorkflowReportTests(unittest.TestCase):
    def report_section(self, report: str, heading: str) -> str:
        return report.split(heading, 1)[1].split("\n## ", 1)[0]

    def fixture_score(self) -> dict[str, object]:
        state = json.loads((CASE_DIR / "state.json").read_text(encoding="utf-8"))
        ledger = [
            json.loads(line)
            for line in (CASE_DIR / "ledger.jsonl").read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        return report_completeness_score(state, ledger)

    def test_replay_fixture_matches_golden_and_surfaces_review_risks(self) -> None:
        result = run_case(CASE_DIR)

        self.assertTrue(result.golden_match)
        self.assertTrue(result.payload["passed"])
        self.assertGreaterEqual(result.payload["report_score"], 0.95)
        self.assertLessEqual(result.payload["report_score"], 1.0)

        risks_section = self.report_section(result.generated_report, "## Risks / Follow-ups")
        consensus_section = self.report_section(result.generated_report, "## Consensus")
        task_graph_section = self.report_section(result.generated_report, "## Task Graph")
        components = self.fixture_score()["components"]

        self.assertIn("- **T001**: Create replay case descriptor (complete)", task_graph_section)
        self.assertIn("- **T005**: Refresh golden report after renderer change (blocked)", task_graph_section)
        self.assertIn("Latest checkpoint: complete", task_graph_section)
        self.assertGreater(components["changed_files_attributed"]["score"], 0)
        self.assertGreater(components["prompt_log_pairs_complete"]["score"], 0)
        self.assertGreater(components["gate_result_present"]["score"], 0)
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
