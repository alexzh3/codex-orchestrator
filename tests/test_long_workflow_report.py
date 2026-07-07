from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from codex_orchestrator.report import prompt_log_pair_ratio, report_completeness_score
from tests.replay_support import run_case


CASE_DIR = ROOT / "tests" / "replay" / "long-run-001"


class LongWorkflowReportTests(unittest.TestCase):
    def report_section(self, report: str, heading: str) -> str:
        return report.split(heading, 1)[1].split("\n## ", 1)[0]

    def fixture_ledger(self) -> list[dict[str, object]]:
        return [
            json.loads(line)
            for line in (CASE_DIR / "ledger.jsonl").read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]

    def fixture_score(self) -> dict[str, object]:
        state = json.loads((CASE_DIR / "state.json").read_text(encoding="utf-8"))
        return report_completeness_score(state, self.fixture_ledger())

    def test_replay_fixture_matches_golden_and_surfaces_review_risks(self) -> None:
        result = run_case(CASE_DIR)

        self.assertTrue(result.golden_match)
        self.assertTrue(result.payload["passed"])
        self.assertGreaterEqual(result.payload["report_score"], 0.95)
        self.assertLessEqual(result.payload["report_score"], 1.0)

        risks_section = self.report_section(result.generated_report, "## Risks / Follow-ups")
        consensus_section = self.report_section(result.generated_report, "## Consensus")
        gate_section = self.report_section(result.generated_report, "## Gate Result")
        orchestration_graph_section = self.report_section(result.generated_report, "## Orchestration Graph")
        ledger = self.fixture_ledger()
        session_dispatch = [record for record in ledger if record.get("type") == "session_dispatch"]
        components = self.fixture_score()["components"]

        self.assertIn("- Reviews: 2", result.generated_report)
        self.assertIn("```mermaid\nflowchart TD", orchestration_graph_section)
        self.assertIn('A_CLAUDE{{"Claude Code<br/>planner · orchestrator"}}', orchestration_graph_section)
        self.assertIn('A_CODEX_EXEC_A[["codex-exec-a · implementer<br/>session 1<br/>exec · complete"]]', orchestration_graph_section)
        self.assertIn('A_CODEX_IDE_REVIEW[["codex-ide-review<br/>session 1<br/>ide · idle"]]', orchestration_graph_section)
        self.assertIn('T001["T001: Create replay case descriptor (complete)"]:::ok', orchestration_graph_section)
        self.assertIn('T005["T005: Refresh golden report after ren… (blocked)"]:::bad', orchestration_graph_section)
        self.assertIn('V1[/"V1 · test: failed"/]:::bad', orchestration_graph_section)
        self.assertIn('R2[/"R2 · diff review: passed"/]:::ok', orchestration_graph_section)
        self.assertIn('C1{"consensus: user_action_required"}:::attention', orchestration_graph_section)
        self.assertIn('A_CLAUDE -->|"dispatch ×2"| A_CODEX_EXEC_A', orchestration_graph_section)
        self.assertIn('A_CODEX_EXEC_A ==>|"complete"| T001', orchestration_graph_section)
        self.assertIn('A_CODEX_EXEC_A ==>|"blocked"| T005', orchestration_graph_section)
        self.assertIn("T005 --> R2", orchestration_graph_section)
        self.assertNotIn('"review"', orchestration_graph_section)
        self.assertNotIn('"add_verification"', orchestration_graph_section)
        self.assertNotIn('"reviews"', orchestration_graph_section)
        self.assertNotIn('"covers"', orchestration_graph_section)
        self.assertIn('G{"gate: blocked"}:::bad', orchestration_graph_section)
        self.assertIn('G -->|"blocked: failed verification remains"| A_CLAUDE', orchestration_graph_section)
        self.assertIn("classDef ok fill:#dcefdc,stroke:#0ca30c,color:#10320f", orchestration_graph_section)
        self.assertIn("classDef attention fill:#fdeecd,stroke:#b97b00,color:#3d2b00", orchestration_graph_section)
        self.assertIn("classDef bad fill:#f8d7d7,stroke:#d03b3b,color:#3f0f0f", orchestration_graph_section)
        self.assertNotIn("agent_claude", orchestration_graph_section)
        self.assertNotIn("A_CLAUDE_2", orchestration_graph_section)
        self.assertIn("- **T001**: Create replay case descriptor (complete)", orchestration_graph_section)
        self.assertIn(
            "- **T005**: Refresh golden report after renderer change (blocked)",
            orchestration_graph_section,
        )
        self.assertIn("Latest checkpoint: complete", orchestration_graph_section)
        self.assertEqual(len(session_dispatch), 1)
        self.assertEqual(prompt_log_pair_ratio(session_dispatch), 1.0)
        self.assertEqual(
            prompt_log_pair_ratio([{"type": "session_dispatch", "prompt_path": "prompts/missing-log.md"}]),
            0.0,
        )
        self.assertGreater(components["changed_files_attributed"]["score"], 0)
        self.assertGreater(components["prompt_log_pairs_complete"]["score"], 0)
        self.assertGreater(components["gate_result_present"]["score"], 0)
        self.assertEqual(components["final_review_present"]["score"], 1.0)
        self.assertIn(
            "- Test (failed): Replay smoke test failed on stale parser warning assertion",
            risks_section,
        )
        self.assertIn("- Session codex-ide-review has low parser confidence.", risks_section)
        self.assertIn("### Reviews", consensus_section)
        self.assertIn("- **R1 — Manual / agent review** (passed)", consensus_section)
        self.assertIn("- **R2 — Diff Review** (passed)", consensus_section)
        self.assertIn("Typed review passed after checking the refreshed report output.", consensus_section)
        self.assertIn(
            "Final Codex review passed with the failed verification documented",
            consensus_section,
        )
        self.assertIn("- OK: `false`", gate_section)
        self.assertIn("- Blocking:", gate_section)
        self.assertIn("  - failed verification remains", gate_section)
        self.assertIn("  - user-action consensus item remains", gate_section)
        self.assertIn("- Warnings: none", gate_section)


if __name__ == "__main__":
    unittest.main()
