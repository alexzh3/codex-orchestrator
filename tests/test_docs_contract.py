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
    for directory in ("docs", "skills"):
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


def jsonl_records(text: str) -> list[dict[str, object]]:
    return [
        json.loads(line)
        for block in jsonl_blocks(text)
        for _, line in block
        if line.strip()
    ]


class DocumentationContractTests(unittest.TestCase):
    def test_skills_are_not_duplicated_by_command_stubs(self) -> None:
        self.assertEqual(list((ROOT / "commands").glob("*.md")), [])

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

    def test_readme_usage_examples_a_focused_independent_review(self) -> None:
        readme = (ROOT / "README.md").read_text(encoding="utf-8")

        self.assertIn("/codex-orchestrator:orchestrate", readme)
        self.assertIn("fresh Codex agent review commit <sha>", readme)
        self.assertIn("Independently verify every material finding", readme)

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

    def test_workflow_initializes_an_ignored_run_with_a_git_baseline(self) -> None:
        workflow = (ROOT / "skills/workflow/SKILL.md").read_text(encoding="utf-8")
        contract = (ROOT / "docs/orchestration-contract.md").read_text(encoding="utf-8")

        for text in (
            "git rev-parse --show-toplevel",
            "git rev-parse --git-path info/exclude",
            "'/.codex-orchestrator/'",
            "git check-ignore -q .codex-orchestrator/.ignore-check",
            "git rev-parse HEAD",
            "git branch --show-current",
            "git status --short --untracked-files=all",
        ):
            self.assertIn(text, workflow)
        self.assertEqual(workflow.count("grep -qxF '/.codex-orchestrator/'"), 2)
        self.assertIn("do not edit the tracked `.gitignore`", workflow)
        self.assertIn("Do not create the run unless both exclude checks succeed", workflow)
        self.assertLess(
            workflow.index("git check-ignore -q"),
            workflow.index("create `.codex-orchestrator/runs/<run-id>/journal.jsonl`"),
        )
        records = jsonl_records(contract)
        run_started = next(record for record in records if record["type"] == "run_started")
        self.assertTrue(Path(run_started["repo"]).is_absolute())
        for field in ("goal", "repo_head", "repo_branch", "repo_status"):
            self.assertIn(field, run_started)

    def test_execution_records_its_worktree_and_ref_before_launch(self) -> None:
        orchestrate = (ROOT / "skills/orchestrate/SKILL.md").read_text(encoding="utf-8")
        monitoring = (ROOT / "skills/orchestrate/references/monitoring.md").read_text(
            encoding="utf-8"
        )
        contract = (ROOT / "docs/orchestration-contract.md").read_text(encoding="utf-8")

        self.assertIn("absolute worktree, full HEAD", orchestrate)
        self.assertIn("absolute `worktree`, full `head`", monitoring)
        self.assertIn("git -C <worktree> rev-parse --show-toplevel", monitoring)
        records = jsonl_records(contract)
        execution = next(record for record in records if record["type"] == "execution")
        self.assertTrue(Path(execution["worktree"]).is_absolute())
        for field in ("worktree", "head", "branch"):
            self.assertIn(field, execution)
        self.assertIn("Read the absolute `worktree` from the preceding execution", monitoring)
        self.assertIn("do not check out or reset to it", monitoring)

    def test_resumed_agent_uses_the_next_execution_directory(self) -> None:
        monitoring = (ROOT / "skills/orchestrate/references/monitoring.md").read_text(
            encoding="utf-8"
        )
        resume = monitoring.split(
            "Resume a relevant idle session as the next execution under the same agent:",
            maxsplit=1,
        )[1]

        self.assertIn('/abs/run-dir/codex-impl-01/execution-02/handoff.md', resume)
        self.assertIn('/abs/run-dir/codex-impl-01/execution-02/prompt.md', resume)
        self.assertIn('/abs/run-dir/codex-impl-01/execution-02/events.jsonl', resume)
        self.assertIn('Do not pass `-C` together with `resume`', resume)

    def test_journal_uniqueness_and_successor_run_guidance_match_runtime(self) -> None:
        contract = " ".join(
            (ROOT / "docs/orchestration-contract.md").read_text(encoding="utf-8").split()
        )
        workflow = " ".join(
            (ROOT / "skills/workflow/SKILL.md").read_text(encoding="utf-8").split()
        )

        self.assertIn("Task IDs intentionally repeat", contract)
        self.assertIn(
            "`verification` and `decision` IDs must each be unique within their entry type",
            contract,
        )
        self.assertIn("retain the journal", contract)
        self.assertIn("Never rewrite journal history", workflow)
        self.assertIn("retain the run and start a successor", workflow)

    def test_historical_benchmark_distinguishes_target_from_release_tag(self) -> None:
        benchmarks = " ".join(
            (ROOT / "docs/benchmarks.md").read_text(encoding="utf-8").split()
        )

        self.assertIn("0.4.1 benchmark target (`01a524f`", benchmarks)
        self.assertIn("release tag `v0.4.1` points to `9000779`", benchmarks)

    def test_validation_is_documented_as_an_omission_check_not_a_schema(self) -> None:
        contract = (ROOT / "docs" / "orchestration-contract.md").read_text(encoding="utf-8")

        self.assertIn("small omission check", contract)
        self.assertIn("does not enforce every documented field", contract)

    def test_verification_and_independent_review_use_different_context(self) -> None:
        review = " ".join(
            (ROOT / "skills/orchestrate/references/review.md")
            .read_text(encoding="utf-8")
            .casefold()
            .split()
        )
        orchestrate = " ".join(
            (ROOT / "skills/orchestrate/SKILL.md")
            .read_text(encoding="utf-8")
            .casefold()
            .split()
        )

        self.assertIn("read the handoff as claims", review)
        self.assertIn("observed check", review)
        self.assertIn("fresh named `codex-review-nn` agent", review)
        self.assertIn("never resume the implementation session", review)
        for excluded in (
            "implementer handoff",
            "claimed test results",
            "earlier review verdicts",
            "claude's tentative conclusion",
        ):
            self.assertIn(excluded, review)
        self.assertIn("for an independent review, start a fresh agent", orchestrate)
        self.assertIn("native session", orchestrate)

    def test_review_uses_plain_exec_with_an_exact_sha_prompt(self) -> None:
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

        self.assertIn("exact commit sha", review)
        self.assertIn("plain `codex exec`", review)
        self.assertIn("for an uncommitted review", review)
        self.assertIn("base head sha", review)
        self.assertNotIn(" review --json", review)
        self.assertNotIn("--commit", review)
        self.assertIn("reserve only its task's `files` and shared resources", compute)
        self.assertIn("disjoint work may continue", compute)
        self.assertIn("separate worktree or committed snapshot", compute)

    def test_consensus_and_decisions_use_evidence_not_agent_count(self) -> None:
        consensus = " ".join(
            (ROOT / "skills/orchestrate/references/consensus.md")
            .read_text(encoding="utf-8")
            .casefold()
            .split()
        )

        for outcome in ("consensus", "claude_decision", "user_action_required"):
            self.assertIn(f"`{outcome}`", consensus)
        for criterion in ("acceptance fit", "direct evidence", "reversibility", "not agent count"):
            self.assertIn(criterion, consensus)

    def test_compute_gating_includes_gpu_utilization_and_process_checks(self) -> None:
        compute = (ROOT / "skills/orchestrate/references/compute.md").read_text(encoding="utf-8")

        self.assertIn("nvidia-smi --query-gpu=memory.used,memory.total", compute)
        self.assertIn("nvidia-smi --query-compute-apps=pid,used_memory", compute)

    def test_focused_cycle_defines_task_outcomes(self) -> None:
        orchestrate = " ".join(
            (ROOT / "skills/orchestrate/SKILL.md")
            .read_text(encoding="utf-8")
            .casefold()
            .split()
        )

        self.assertIn("append `complete` when they are satisfied", orchestrate)
        self.assertIn(
            "`failed` when they are conclusively unmet and no in-scope recovery remains",
            orchestrate,
        )
        self.assertIn("`blocked` when a user or external dependency prevents", orchestrate)
        self.assertIn("otherwise keep the task `active`", orchestrate)

    def test_accepted_worktree_changes_are_reverified_in_the_target(self) -> None:
        compute = " ".join(
            (ROOT / "skills/orchestrate/references/compute.md")
            .read_text(encoding="utf-8")
            .casefold()
            .split()
        )

        self.assertIn("integrate its commits into the target", compute)
        self.assertIn("rerun the affected acceptance checks there", compute)
        self.assertIn("only after those target checks pass", compute)

    def test_replay_directory_is_documented_as_a_generated_test_scaffold(self) -> None:
        contract = " ".join(
            (ROOT / "docs/orchestration-contract.md").read_text(encoding="utf-8").split()
        )

        self.assertIn("checked-in input scaffold, not a standalone valid closed run", contract)
        self.assertIn("test_prompt_first_workflow.py", contract)
        self.assertIn("validates the completed copy", contract)

    def test_review_effort_is_risk_scaled(self) -> None:
        review = " ".join(
            (ROOT / "skills/orchestrate/references/review.md")
            .read_text(encoding="utf-8")
            .casefold()
            .split()
        )
        workflow = " ".join(
            (ROOT / "skills/workflow/SKILL.md").read_text(encoding="utf-8").casefold().split()
        )

        self.assertIn("distinct unresolved question", review)
        orchestrate = " ".join(
            (ROOT / "skills/orchestrate/SKILL.md").read_text(encoding="utf-8").casefold().split()
        )
        self.assertIn("fresh agent and native session", orchestrate)
        self.assertIn("hard-to-reverse design choice", workflow)
        self.assertIn("only the goal, constraints, and acceptance criteria", workflow)
        self.assertIn("using evidence rather than agent count", workflow)
        self.assertIn("distinct unresolved question", orchestrate)
        self.assertIn("do not repeat identical reviews", orchestrate)
        self.assertNotIn("unanchored alternative", workflow)

    def test_workflow_owns_the_complete_run_and_delegates_focused_cycles(self) -> None:
        orchestrate = (ROOT / "skills/orchestrate/SKILL.md").read_text(encoding="utf-8")
        workflow = (ROOT / "skills/workflow/SKILL.md").read_text(encoding="utf-8")

        self.assertIn("This skill owns the lifecycle from planning", workflow)
        self.assertIn("Claude turns the goal into a concrete plan", workflow)
        self.assertIn("review as a task and focused agent cycle", workflow)
        self.assertIn("use the orchestrate skill", workflow)
        self.assertIn("Focused Agent Cycle", orchestrate)
        self.assertIn("Save the exact prompt and append `execution` before launch", orchestrate)
        self.assertNotIn("This skill owns the run protocol", orchestrate)
        self.assertNotIn("`run_started`", orchestrate)
        self.assertNotIn("`run_closed`", orchestrate)

    def test_docs_exclude_removed_ide_and_observe_workflows(self) -> None:
        operational_docs = "\n".join(
            (ROOT / path).read_text(encoding="utf-8").casefold()
            for path in (
                "README.md",
                "docs/orchestration-contract.md",
                "skills/orchestrate/SKILL.md",
                "skills/workflow/SKILL.md",
                "skills/orchestrate/references/monitoring.md",
            )
        )

        self.assertNotIn("event_source: \"ide\"", operational_docs)
        self.assertNotIn("mode: \"observe\"", operational_docs)
        self.assertNotIn("codex://threads/", operational_docs)

    def test_documented_codex_commands_need_no_undefined_override(self) -> None:
        review = (ROOT / "skills/orchestrate/references/review.md").read_text(
            encoding="utf-8"
        )
        references = "\n".join(
            (ROOT / path).read_text(encoding="utf-8")
            for path in (
                "skills/orchestrate/references/monitoring.md",
                "skills/orchestrate/references/review.md",
            )
        )

        self.assertNotIn("$CODEX", references)
        self.assertIn("codex exec", references)
        self.assertIn('EXECUTION_DIR=".codex-orchestrator/runs/<run-id>/', review)

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
