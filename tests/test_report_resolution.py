from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "codex_orch.py"


class ReportResolutionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self.tmp.name)
        self.run_cli("init", "--repo", str(self.repo), "--run-id", "run")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def run_cli(self, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
        result = subprocess.run(
            [sys.executable, str(SCRIPT), *args],
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=self.repo,
        )
        if check and result.returncode != 0:
            self.fail(f"command failed: {result.args}\nstdout={result.stdout}\nstderr={result.stderr}")
        return result

    def ledger_dir(self) -> Path:
        return self.repo / ".codex-orchestrator" / "runs" / "run"

    def append_event(self, event: dict[str, object]) -> None:
        self.run_cli("append-event", "--repo", str(self.repo), "--run-id", "run", json.dumps(event))

    def render_report(self) -> str:
        self.run_cli("report", "--repo", str(self.repo), "--run-id", "run")
        return (self.ledger_dir() / "report.md").read_text(encoding="utf-8")

    def report_section(self, report: str, heading: str) -> str:
        return report.split(heading, 1)[1].split("\n## ", 1)[0]

    def test_decisions_render_basis_clears_and_evidence_refs(self) -> None:
        self.append_event(
            {
                "type": "verification",
                "id": "V1",
                "kind": "test",
                "result": "failed",
                "summary": "Unit tests failed.",
                "command": "python3 -m unittest",
            }
        )
        self.append_event(
            {
                "type": "verification",
                "id": "V2",
                "kind": "test",
                "result": "passed",
                "summary": "Unit tests passed on rerun.",
                "command": "python3 -m unittest",
            }
        )
        self.append_event(
            {
                "type": "consensus",
                "finding": "Unit tests failed.",
                "outcome": "consensus",
                "resolution": "The rerun passed.",
                "resolution_basis": "rerun_passed",
                "evidence": ["rerun output"],
                "clears": ["verification:V1"],
                "evidence_refs": ["verification:V2"],
            }
        )

        report = self.render_report()
        consensus = self.report_section(report, "## Consensus")

        self.assertIn("  - **Outcome:** consensus", consensus)
        self.assertIn("  - **Basis:** rerun passed", consensus)
        self.assertIn("  - **Clears:**\n    - `verification:V1`", consensus)
        self.assertIn("  - **Evidence Refs:**\n    - `verification:V2`", consensus)

    def test_accepted_risks_section_lists_overrides_with_target_flags(self) -> None:
        self.append_event(
            {
                "type": "verification",
                "id": "V1",
                "kind": "test",
                "result": "failed",
                "summary": "Executable check failed.",
                "command": "python3 -m unittest",
            }
        )
        self.append_event(
            {
                "type": "verification",
                "id": "V2",
                "kind": "manual_review",
                "result": "failed",
                "summary": "Acceptance review failed.",
                "acceptance_test": True,
            }
        )
        self.append_event(
            {
                "type": "consensus",
                "finding": "Style convention accepted.",
                "outcome": "consensus",
                "resolution": "Accepted as a tracked risk.",
                "resolution_basis": "accepted_risk",
                "evidence": ["review"],
                "clears": ["verification:V1", "verification:V404", "finding:F1"],
            }
        )
        self.append_event(
            {
                "type": "consensus",
                "finding": "Human override recorded.",
                "outcome": "claude_decision",
                "resolution": "Human explicitly approved.",
                "resolution_basis": "user_override",
                "evidence": ["user approval"],
                "clears": ["verification:V2"],
            }
        )

        report = self.render_report()
        summary = self.report_section(report, "## Summary")
        consensus = self.report_section(report, "## Consensus")

        self.assertIn("- Accepted Risks: 1", summary)
        self.assertIn("- User Overrides: 1", summary)
        self.assertLess(consensus.index("### Accepted Risks & Overrides"), consensus.index("### Decisions"))
        self.assertIn("- **Accepted Risk:** Style convention accepted.", consensus)
        self.assertIn("  - Clears `verification:V1` (executable: yes, acceptance: no)", consensus)
        self.assertIn("  - Clears `verification:V404` (unknown verification)", consensus)
        self.assertIn("  - Clears `finding:F1`", consensus)
        self.assertIn("- **User Override:** Human override recorded.", consensus)
        self.assertIn("  - Clears `verification:V2` (executable: no, acceptance: yes)", consensus)

    def test_typed_review_renders_blocking_findings(self) -> None:
        self.append_event(
            {
                "type": "review",
                "task_id": "task-a",
                "reviewer": "claude",
                "kind": "diff",
                "result": "failed",
                "summary": "Review found a blocker.",
                "blocking_findings": [
                    {
                        "id": "F1",
                        "claim": "The patch can fail at runtime.",
                        "severity": "P0",
                        "repro_command": "python3 -m unittest tests.test_report_resolution -v",
                    },
                    {
                        "id": "F2",
                        "claim": "The fallback needs a note.",
                    },
                ],
            }
        )

        report = self.render_report()
        consensus = self.report_section(report, "## Consensus")

        self.assertIn("  - Blocking Findings:", consensus)
        self.assertIn(
            "    - [P0] F1: The patch can fail at runtime. "
            "(repro: `python3 -m unittest tests.test_report_resolution -v`)",
            consensus,
        )
        self.assertIn("    - [P1] F2: The fallback needs a note.", consensus)

    def test_report_without_new_fields_is_unchanged(self) -> None:
        self.append_event(
            {
                "type": "review",
                "task_id": "task-a",
                "reviewer": "claude",
                "kind": "diff",
                "result": "passed",
                "summary": "Legacy review.",
                "findings": [],
            }
        )
        self.append_event(
            {
                "type": "consensus",
                "finding": "Legacy finding.",
                "outcome": "consensus",
                "resolution": "Legacy consensus.",
                "evidence": ["review"],
            }
        )

        report = self.render_report()

        self.assertNotIn("### Accepted Risks & Overrides", report)
        self.assertNotIn("  - **Basis:**", report)
        self.assertNotIn("  - **Clears:**", report)
        self.assertNotIn("  - **Evidence Refs:**", report)
        self.assertNotIn("- Accepted Risks:", report)
        self.assertNotIn("- User Overrides:", report)
        self.assertNotIn("  - Blocking Findings:", report)


if __name__ == "__main__":
    unittest.main()
