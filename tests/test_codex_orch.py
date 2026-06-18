from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "codex_orch.py"
REPORT_HEADINGS = [
    "## Summary",
    "## Changes",
    "## Evidence",
    "## Consensus",
    "## Risks / Follow-ups",
]


class CodexOrchCliTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self.tmp.name)

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

    def ledger_dir(self, run_id: str = "run") -> Path:
        return self.repo / ".codex-orchestrator" / "runs" / run_id

    def init_run(self) -> None:
        self.run_cli("init", "--run-id", "run", "--repo", str(self.repo))

    def report_section(self, report: str, heading: str) -> str:
        return report.split(heading, 1)[1].split("\n## ", 1)[0]

    def update_state(self, **updates: object) -> None:
        path = self.ledger_dir() / "state.json"
        state = json.loads(path.read_text(encoding="utf-8"))
        state.update(updates)
        path.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    def test_init_creates_ledger(self) -> None:
        result = self.run_cli("init", "--run-id", "run", "--repo", str(self.repo))
        payload = json.loads(result.stdout)

        self.assertTrue(payload["ok"])
        self.assertTrue((self.ledger_dir() / "state.json").is_file())
        self.assertTrue((self.ledger_dir() / "ledger.jsonl").is_file())
        self.assertTrue((self.ledger_dir() / "report.md").is_file())
        self.assertTrue((self.ledger_dir() / "prompts").is_dir())
        self.assertTrue((self.ledger_dir() / "logs").is_dir())
        self.assertTrue((self.ledger_dir() / "artifacts").is_dir())
        self.assertTrue(payload["created_or_replaced"]["prompts/"])
        self.assertTrue(payload["created_or_replaced"]["logs/"])
        self.assertTrue(payload["created_or_replaced"]["artifacts/"])
        report = (self.ledger_dir() / "report.md").read_text(encoding="utf-8")
        self.assertEqual(report, "# Report\n\n" + "\n\n".join(REPORT_HEADINGS) + "\n\n")
        state = json.loads((self.ledger_dir() / "state.json").read_text(encoding="utf-8"))
        self.assertNotIn("verification_policy", state)
        self.assertFalse((self.ledger_dir() / "events.jsonl").exists())
        self.assertFalse((self.ledger_dir() / "tasks.json").exists())
        self.assertFalse((self.ledger_dir() / "verification.jsonl").exists())
        self.assertFalse((self.ledger_dir() / "consensus.md").exists())
        self.assertFalse((self.ledger_dir() / "final-report.md").exists())

    def test_add_verification_and_status(self) -> None:
        self.init_run()
        self.run_cli(
            "add-verification",
            "--run-id",
            "run",
            "--kind",
            "test",
            "--command",
            "python3 -m unittest discover -s tests -v",
            "--exit-code",
            "0",
            "--result",
            "passed",
            "--summary",
            "Unit tests passed",
        )

        records = [
            json.loads(line)
            for line in (self.ledger_dir() / "ledger.jsonl").read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        self.assertEqual(records[0]["type"], "verification")
        self.assertEqual(records[0]["kind"], "test")
        self.assertEqual(records[0]["result"], "passed")

        status = json.loads(self.run_cli("status", "--run-id", "run").stdout)
        self.assertEqual(status["latest_verification"]["summary"], "Unit tests passed")
        self.assertIn("recommended_next_action", status)

    def test_append_event_writes_typed_ledger_record(self) -> None:
        self.init_run()
        result = subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                "append-event",
                "--run-id",
                "run",
                '{"summary":"smoke"}',
            ],
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=self.repo,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertTrue(payload["ok"])
        self.assertEqual(Path(payload["ledger_path"]).name, "ledger.jsonl")
        records = [
            json.loads(line)
            for line in (self.ledger_dir() / "ledger.jsonl").read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        self.assertEqual(records[0]["type"], "event")
        self.assertEqual(records[0]["summary"], "smoke")

    def test_report_records_missing_and_present_evidence(self) -> None:
        self.init_run()
        self.run_cli("report", "--run-id", "run")
        report = (self.ledger_dir() / "report.md").read_text(encoding="utf-8")
        summary_section = self.report_section(report, "## Summary")
        top_level_headings = [line for line in report.splitlines() if line.startswith("## ")]
        self.assertEqual(top_level_headings, REPORT_HEADINGS)
        self.assertIn("No authored summary recorded.", summary_section)
        self.assertIn("### Generated Digest", summary_section)
        self.assertIn("- Run ID: run", summary_section)
        self.assertIn("- Status: active", summary_section)
        self.assertIn("- Acceptance: No acceptance decision recorded; this run needs review.", summary_section)
        self.assertIn("- Changes: none", summary_section)
        self.assertIn("- Evidence: none recorded", summary_section)
        self.assertIn("- Reviews: 0", summary_section)
        self.assertIn("- Consensus: none", summary_section)
        self.assertIn("- Open items: none", summary_section)
        self.assertIn("No authored changes recorded.", self.report_section(report, "## Changes"))
        self.assertIn("No evidence recorded.", report)
        self.assertNotIn("## Final Report", report)

        self.run_cli(
            "add-verification",
            "--run-id",
            "run",
            "--kind",
            "manual_review",
            "--result",
            "needs_human_review",
            "--summary",
            "Parser warning requires manual inspection",
        )
        self.run_cli("report", "--run-id", "run")
        report = (self.ledger_dir() / "report.md").read_text(encoding="utf-8")
        summary_section = self.report_section(report, "## Summary")
        self.assertIn("Parser warning requires manual inspection", report)
        self.assertIn("- Evidence: none recorded", summary_section)
        self.assertIn("- Reviews: 1", summary_section)
        self.assertIn("- Open items (1):", summary_section)
        self.assertIn(
            "  - Manual / agent review (needs_human_review): Parser warning requires manual inspection",
            summary_section,
        )
        self.assertIn("No acceptance decision recorded", report)
        risks_section = self.report_section(report, "## Risks / Follow-ups")
        self.assertIn("- Manual / agent review (needs_human_review): Parser warning requires manual inspection", risks_section)

    def test_report_shows_review_placeholder_without_records(self) -> None:
        self.init_run()
        self.run_cli("report", "--run-id", "run")
        report = (self.ledger_dir() / "report.md").read_text(encoding="utf-8")

        self.assertIn("No consensus decisions recorded.", report)

    def test_report_renders_manual_review_under_consensus_section(self) -> None:
        self.init_run()
        summary = "Independent Codex review: no regressions"
        self.run_cli(
            "add-verification",
            "--run-id",
            "run",
            "--kind",
            "manual_review",
            "--result",
            "passed",
            "--summary",
            summary,
            "--command",
            "codex exec review --uncommitted",
            "--exit-code",
            "0",
            "--artifact",
            "prompts/final-review.md",
            "--artifact",
            "logs/final-review.jsonl",
            "--notes",
            "No blocking findings.",
        )
        self.run_cli("report", "--run-id", "run")
        report = (self.ledger_dir() / "report.md").read_text(encoding="utf-8")
        consensus_section = self.report_section(report, "## Consensus")

        self.assertIn(summary, report)
        self.assertIn("### Reviews", report)
        self.assertIn(summary, consensus_section)
        self.assertIn("- **Manual / agent review** (passed)", consensus_section)
        self.assertIn("  - Command: `codex exec review --uncommitted`", consensus_section)
        self.assertIn("  - Exit Code: `0`", consensus_section)
        self.assertIn("  - Artifacts:", consensus_section)
        self.assertIn("    - `prompts/final-review.md`", consensus_section)
        self.assertIn("    - `logs/final-review.jsonl`", consensus_section)
        self.assertIn("  - Notes: No blocking findings.", consensus_section)
        self.assertNotIn("No consensus decisions recorded.", report)

    def test_report_keeps_automated_evidence_under_verification(self) -> None:
        self.init_run()
        summary = "Unit test suite passed under Python"
        self.run_cli(
            "add-verification",
            "--run-id",
            "run",
            "--kind",
            "test",
            "--command",
            "python3 -m unittest discover -s tests -v",
            "--exit-code",
            "0",
            "--artifact",
            "logs/tests.txt",
            "--notes",
            "Full suite green.",
            "--result",
            "passed",
            "--summary",
            summary,
        )
        self.run_cli("report", "--run-id", "run")
        report = (self.ledger_dir() / "report.md").read_text(encoding="utf-8")
        evidence_section = self.report_section(report, "## Evidence")

        self.assertIn("- **Test** (passed)", evidence_section)
        self.assertIn(summary, evidence_section)
        self.assertIn("  - Command: `python3 -m unittest discover -s tests -v`", evidence_section)
        self.assertIn("  - Exit Code: `0`", evidence_section)
        self.assertIn("  - Notes: Full suite green.", evidence_section)
        self.assertIn("  - Artifacts:", evidence_section)
        self.assertIn("    - `logs/tests.txt`", evidence_section)
        self.assertIn("- Evidence: 1 passed", self.report_section(report, "## Summary"))

    def test_report_shows_consensus_placeholder_without_records(self) -> None:
        self.init_run()
        self.run_cli("report", "--run-id", "run")
        report = (self.ledger_dir() / "report.md").read_text(encoding="utf-8")

        self.assertIn("No consensus decisions recorded.", report)

    def test_report_renders_consensus_record_without_placeholder(self) -> None:
        self.init_run()
        self.run_cli("report", "--run-id", "run")
        finding = "Consensus finding from ledger"
        resolution = "Render rich consensus records without the placeholder"
        self.run_cli(
            "append-event",
            "--run-id",
            "run",
            json.dumps(
                {
                    "type": "consensus",
                    "finding": finding,
                    "root_cause": "The report generator reused generated placeholder text.",
                    "resolution": resolution,
                    "status": "resolved",
                    "evidence": ["report.md omits stale placeholder", "ledger record is rendered"],
                }
            ),
        )

        self.run_cli("report", "--run-id", "run")
        report = (self.ledger_dir() / "report.md").read_text(encoding="utf-8")

        self.assertNotIn("No consensus decisions recorded.", report)
        self.assertIn(finding, report)
        self.assertIn(resolution, report)

    def test_report_flags_open_risks_in_accepted_run(self) -> None:
        self.init_run()
        self.update_state(
            status="accepted",
            sessions=[{"name": "codex-a", "status": "unknown", "mode": "exec"}],
        )
        self.run_cli(
            "add-verification",
            "--run-id",
            "run",
            "--kind",
            "test",
            "--result",
            "failed",
            "--summary",
            "Unit tests failed",
        )
        self.run_cli(
            "append-event",
            "--run-id",
            "run",
            json.dumps(
                {
                    "type": "consensus",
                    "finding": "Accepted consensus finding",
                    "status": "accepted",
                }
            ),
        )
        self.run_cli(
            "append-event",
            "--run-id",
            "run",
            json.dumps(
                {
                    "type": "consensus",
                    "finding": "Consensus requires owner decision",
                    "status": "deferred",
                }
            ),
        )

        self.run_cli("report", "--run-id", "run")
        report = (self.ledger_dir() / "report.md").read_text(encoding="utf-8")
        summary_section = self.report_section(report, "## Summary")
        risks_section = self.report_section(report, "## Risks / Follow-ups")

        self.assertIn("Accepted, but 3 unresolved item(s) remain — see Risks / Follow-ups.", report)
        self.assertIn(
            "- Acceptance: Accepted, but 3 unresolved item(s) remain — see Risks / Follow-ups.",
            summary_section,
        )
        self.assertIn("- Evidence: 1 failed", summary_section)
        self.assertIn("- Reviews: 0", summary_section)
        self.assertIn("- Consensus: 1 accepted, 1 deferred", summary_section)
        self.assertIn("- Sessions: 1", summary_section)
        self.assertIn("- Open items (3):", summary_section)
        self.assertIn("  - Consensus requires owner decision (deferred)", summary_section)
        self.assertIn("- Session codex-a has unknown status.", risks_section)
        self.assertIn("- Test (failed): Unit tests failed", risks_section)
        self.assertIn("- Consensus requires owner decision (deferred)", risks_section)

    def test_report_renders_task_changes_and_task_risks(self) -> None:
        self.init_run()
        complete_title = "Implement generated Changes section"
        blocked_title = "Resolve blocked deployment follow-up"
        self.run_cli(
            "append-event",
            "--run-id",
            "run",
            json.dumps(
                {
                    "type": "task",
                    "id": "task-1",
                    "title": complete_title,
                    "status": "complete",
                    "owner": "codex",
                    "notes": "Added task rendering.",
                }
            ),
        )
        self.run_cli(
            "append-event",
            "--run-id",
            "run",
            json.dumps(
                {
                    "type": "task",
                    "id": "task-2",
                    "title": blocked_title,
                    "status": "blocked",
                    "owner": "human",
                    "notes": "Waiting on credentials.",
                }
            ),
        )

        self.run_cli("report", "--run-id", "run")
        report = (self.ledger_dir() / "report.md").read_text(encoding="utf-8")
        summary_section = self.report_section(report, "## Summary")
        changes_section = self.report_section(report, "## Changes")
        risks_section = self.report_section(report, "## Risks / Follow-ups")

        self.assertIn("- Changes: 2 (1 complete, 1 blocked)", summary_section)
        self.assertIn(f"  - {complete_title}", summary_section)
        self.assertIn(f"  - {blocked_title}", summary_section)
        self.assertIn("- Open items (1):", summary_section)
        self.assertIn(f"  - {blocked_title} (blocked)", summary_section)
        self.assertIn("No authored changes recorded.", changes_section)
        self.assertIn("### Ledger Records", changes_section)
        self.assertIn(f"- **{complete_title}** (complete)", changes_section)
        self.assertIn("  - Owner: codex", changes_section)
        self.assertIn("  - Notes: Added task rendering.", changes_section)
        self.assertIn(f"- **{blocked_title}** (blocked)", changes_section)
        self.assertIn("  - Owner: human", changes_section)
        self.assertIn("  - Notes: Waiting on credentials.", changes_section)
        self.assertIn(f"- {blocked_title} (blocked)", risks_section)

    def test_report_preserves_authored_sections_across_runs(self) -> None:
        self.init_run()
        report_path = self.ledger_dir() / "report.md"
        report_path.write_text(
            (
                "# Report\n\n"
                "## Summary\n\n"
                "Claude-authored summary.\n\n"
                "## Changes\n\n"
                "- `scripts/codex_orch.py`: report layout changed.\n\n"
                "## Review\n\n"
                "Manual review note.\n\n"
                "## Consensus\n\n"
                "Manual consensus note.\n\n"
                "## Evidence\n\n"
                "## Risks / Follow-ups\n\n"
            ),
            encoding="utf-8",
        )

        self.run_cli("report", "--run-id", "run")
        first_report = report_path.read_text(encoding="utf-8")
        self.run_cli("report", "--run-id", "run")
        second_report = report_path.read_text(encoding="utf-8")

        self.assertIn("Claude-authored summary.", self.report_section(second_report, "## Summary"))
        self.assertIn(
            "- `scripts/codex_orch.py`: report layout changed.",
            self.report_section(second_report, "## Changes"),
        )
        self.assertIn("Manual review note.", self.report_section(second_report, "## Consensus"))
        self.assertIn("Manual consensus note.", self.report_section(second_report, "## Consensus"))
        self.assertEqual(self.normalized_report(first_report), self.normalized_report(second_report))

    def normalized_report(self, report: str) -> str:
        return "\n".join(
            "Generated at: <timestamp>" if line.startswith("Generated at: ") else line
            for line in report.splitlines()
        )


if __name__ == "__main__":
    unittest.main()
