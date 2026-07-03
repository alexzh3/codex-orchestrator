from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "codex_orch.py"
SCHEMA = ROOT / "schemas" / "codex-task-output.schema.json"


class RenderPromptTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self.tmp.name)
        self.run_cli("init", "--repo", str(self.repo), "--run-id", "run")
        self.run_cli(
            "append-event",
            "--repo",
            str(self.repo),
            "--run-id",
            "run",
            json.dumps(
                {
                    "type": "task_created",
                    "id": "T100",
                    "title": "Implement prompt rendering",
                    "status": "active",
                    "owner": "codex",
                    "files_allowed": ["scripts/codex_orch.py", "tests/test_render_prompt.py"],
                    "files_forbidden": ["scripts/codex_orch_parse.py"],
                    "acceptance": ["render-prompt substitutes fields", "output schema is strict"],
                    "verification_required": ["python3 -m unittest tests/test_render_prompt.py -v"],
                }
            ),
        )

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

    def test_render_prompt_substitutes_task_fields(self) -> None:
        result = self.run_cli("render-prompt", "--repo", str(self.repo), "--run-id", "run", "--task-id", "T100", "--kind", "impl")
        prompt = result.stdout

        self.assertIn("# Codex Implementation Task: T100 - Implement prompt rendering", prompt)
        self.assertIn("You are the implementation agent for task `T100`.", prompt)
        self.assertIn("- scripts/codex_orch.py", prompt)
        self.assertIn("- tests/test_render_prompt.py", prompt)
        self.assertIn("- scripts/codex_orch_parse.py", prompt)
        self.assertIn("- render-prompt substitutes fields", prompt)
        self.assertIn("- python3 -m unittest tests/test_render_prompt.py -v", prompt)
        self.assertIn("schemas/codex-task-output.schema.json", prompt)
        self.assertNotIn("{{", prompt)
        self.assertNotIn("}}", prompt)

    def test_render_prompt_uses_task_goal_context_and_constraints(self) -> None:
        self.run_cli(
            "append-event",
            "--repo",
            str(self.repo),
            "--run-id",
            "run",
            json.dumps(
                {
                    "type": "task_created",
                    "id": "T101",
                    "title": "Fallback title",
                    "status": "active",
                    "goal": "Implement the scoped protocol behavior.",
                    "context": ["Review found task leakage in verification matching."],
                    "constraints": ["Keep event fields optional for old ledgers."],
                }
            ),
        )

        result = self.run_cli("render-prompt", "--repo", str(self.repo), "--run-id", "run", "--task-id", "T101", "--kind", "impl")
        prompt = result.stdout
        goal_section = prompt.split("## Goal", 1)[1].split("\n## Context", 1)[0]

        self.assertIn("Implement the scoped protocol behavior.", goal_section)
        self.assertNotIn("Fallback title", goal_section)
        self.assertIn("## Context\n\n- Review found task leakage in verification matching.", prompt)
        self.assertIn("## Constraints\n\n- Keep event fields optional for old ledgers.", prompt)

    def test_render_prompt_writes_review_prompt_to_out(self) -> None:
        out_path = self.repo / ".codex-orchestrator" / "runs" / "run" / "prompts" / "T100-review.md"

        result = self.run_cli(
            "render-prompt",
            "--repo",
            str(self.repo),
            "--run-id",
            "run",
            "--task-id",
            "T100",
            "--kind",
            "review",
            "--out",
            str(out_path),
        )

        self.assertEqual(result.stdout, "")
        prompt = out_path.read_text(encoding="utf-8")
        self.assertIn("# Codex Review Task: T100 - Implement prompt rendering", prompt)
        self.assertIn("Review the implementation against the task contract", prompt)
        self.assertNotIn("{{", prompt)

    def test_output_schema_is_strict_json_schema(self) -> None:
        schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
        properties = schema["properties"]
        tests_run_items = properties["tests_run"]["items"]

        self.assertEqual(schema["type"], "object")
        self.assertIs(schema["additionalProperties"], False)
        self.assertEqual(set(schema["required"]), set(properties))
        self.assertEqual(properties["summary"]["type"], "string")
        self.assertEqual(properties["files_changed"]["items"]["type"], "string")
        self.assertEqual(properties["unresolved_blockers"]["items"]["type"], "string")
        self.assertEqual(tests_run_items["type"], "object")
        self.assertIs(tests_run_items["additionalProperties"], False)
        self.assertEqual(set(tests_run_items["required"]), set(tests_run_items["properties"]))
        self.assertEqual(tests_run_items["properties"]["command"]["type"], "string")
        self.assertEqual(tests_run_items["properties"]["exit_code"]["type"], ["integer", "null"])
        self.assertEqual(tests_run_items["properties"]["result"]["type"], "string")


if __name__ == "__main__":
    unittest.main()
