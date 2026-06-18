from __future__ import annotations

import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCHEMA = ROOT / "schemas" / "codex-orchestrator.schema.json"


class SchemaTests(unittest.TestCase):
    def test_runtime_schema_bundle_replaces_split_schemas(self) -> None:
        schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
        defs = schema["$defs"]

        self.assertEqual(
            schema["$id"],
            "https://alexzh3.github.io/codex-orchestrator/schemas/codex-orchestrator.schema.json",
        )
        for name in (
            "state",
            "ledger_event",
            "verification_event",
            "consensus_event",
            "task_event",
            "generic_event",
        ):
            self.assertIn(name, defs)
        self.assertNotIn("verification_policy", defs)

        for old_name in (
            "state.schema.json",
            "verification.schema.json",
            "consensus.schema.json",
            "task.schema.json",
        ):
            self.assertFalse((ROOT / "schemas" / old_name).exists())

        consensus = defs["consensus_event"]
        self.assertIn("outcome", consensus["required"])
        self.assertEqual(
            consensus["properties"]["outcome"]["enum"],
            ["consensus", "claude_decision", "user_action_required"],
        )
        self.assertEqual(
            consensus["properties"]["risk_level"]["enum"],
            ["none", "low", "medium", "high"],
        )


if __name__ == "__main__":
    unittest.main()
