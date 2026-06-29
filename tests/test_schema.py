from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from codex_orch_contract import (  # noqa: E402
    ALLOWED_RISK_LEVELS,
    ALLOWED_VERIFICATION_KINDS,
    ALLOWED_VERIFICATION_RESULTS,
    CONSENSUS_OUTCOME_ORDER,
    RUN_META_CONFIG_FIELDS,
    TASK_STATUS_ORDER,
)

SCHEMA = ROOT / "schemas" / "codex-orchestrator.schema.json"
BENCHMARK_SCHEMA = ROOT / "schemas" / "benchmark-result.schema.json"


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
            "run_meta_event",
            "run_meta_config",
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
            list(CONSENSUS_OUTCOME_ORDER),
        )
        self.assertEqual(
            consensus["properties"]["risk_level"]["enum"],
            list(ALLOWED_RISK_LEVELS),
        )
        run_meta = defs["run_meta_event"]
        self.assertEqual(
            run_meta["required"],
            ["type", "recorded_at", "run_id", "protocol_version", "schema_version"],
        )
        self.assertEqual(run_meta["properties"]["type"]["const"], "run_meta")
        self.assertEqual(
            tuple(defs["run_meta_config"]["properties"]),
            RUN_META_CONFIG_FIELDS,
        )
        self.assertIn("run_meta", defs["generic_event"]["properties"]["type"]["not"]["enum"])

    def test_schema_enums_match_runtime_contract(self) -> None:
        defs = json.loads(SCHEMA.read_text(encoding="utf-8"))["$defs"]

        self.assertEqual(
            defs["verification_event"]["properties"]["kind"]["enum"],
            list(ALLOWED_VERIFICATION_KINDS),
        )
        self.assertEqual(
            defs["verification_event"]["properties"]["result"]["enum"],
            list(ALLOWED_VERIFICATION_RESULTS),
        )
        self.assertEqual(
            defs["consensus_event"]["properties"]["outcome"]["enum"],
            list(CONSENSUS_OUTCOME_ORDER),
        )
        self.assertEqual(
            defs["consensus_event"]["properties"]["risk_level"]["enum"],
            list(ALLOWED_RISK_LEVELS),
        )
        self.assertEqual(
            defs["task_event"]["properties"]["status"]["enum"],
            list(TASK_STATUS_ORDER),
        )

    def test_benchmark_result_schema_shape(self) -> None:
        schema = json.loads(BENCHMARK_SCHEMA.read_text(encoding="utf-8"))
        required = [
            "suite",
            "case_id",
            "plugin_ref",
            "repo_commit",
            "passed",
            "wall_seconds",
            "claude_turns",
            "codex_sessions",
            "codex_reviews",
            "manual_interventions",
            "prompt_log_pairs_complete",
            "ledger_errors",
            "gate_passed",
            "report_score",
            "external_score",
        ]

        self.assertEqual(
            schema["$id"],
            "https://alexzh3.github.io/codex-orchestrator/schemas/benchmark-result.schema.json",
        )
        self.assertEqual(schema["required"], required)
        self.assertFalse(schema["additionalProperties"])
        self.assertEqual(schema["properties"]["report_score"]["minimum"], 0)
        self.assertEqual(schema["properties"]["report_score"]["maximum"], 1)


if __name__ == "__main__":
    unittest.main()
