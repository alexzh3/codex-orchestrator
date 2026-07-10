from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXPECTED_VERSION = "0.5.0"


class VersionTests(unittest.TestCase):
    def test_release_metadata_versions_are_consistent(self) -> None:
        plugin = json.loads(
            (ROOT / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8")
        )
        marketplace = json.loads(
            (ROOT / ".claude-plugin" / "marketplace.json").read_text(encoding="utf-8")
        )
        pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
        match = re.search(r'^version = "([^"]+)"$', pyproject, flags=re.MULTILINE)

        self.assertIsNotNone(match, "pyproject.toml must declare project.version")
        self.assertEqual(plugin["version"], EXPECTED_VERSION)
        self.assertEqual(marketplace["plugins"][0]["version"], EXPECTED_VERSION)
        self.assertEqual(match.group(1), EXPECTED_VERSION)


if __name__ == "__main__":
    unittest.main()
