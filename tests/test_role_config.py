from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scripts.codex_orchestrator.role_config import (
    CONFIG_RELATIVE_PATH,
    RoleConfigError,
    initialize_role_config,
    load_role_config,
)

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "codex_orch_tools.py"

VALID_CONFIG = """\
[meta]
version = 1

[defaults]
model = gpt-5.6-sol
speed = fast

[role.implementation]
reasoning_efforts = xhigh, max, ultra

[role.review]
reasoning_efforts = max, ultra

[role.planning]
reasoning_efforts = max, ultra

[role.planning_review]
reasoning_efforts = max, ultra
"""


def init_repo(repo: Path) -> None:
    subprocess.run(["git", "init", "-q", str(repo)], check=True)


def write_config(repo: Path, content: str = VALID_CONFIG) -> Path:
    init_repo(repo)
    path = repo / CONFIG_RELATIVE_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        check=False,
        text=True,
        capture_output=True,
        cwd=ROOT,
    )


class RoleConfigTests(unittest.TestCase):
    def test_missing_configuration_is_disabled_without_creating_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            init_repo(repo)

            config = load_role_config(repo)

            self.assertIsNone(config)
            self.assertFalse((repo / ".codex-orchestrator").exists())

    def test_initialization_creates_defaults_and_local_exclusion_without_overwrite(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            init_repo(repo)

            path = initialize_role_config(repo)
            original = path.read_text(encoding="utf-8")
            exclude = (repo / ".git" / "info" / "exclude").read_text(encoding="utf-8")

            self.assertEqual(original, VALID_CONFIG)
            self.assertIn("/.codex-orchestrator/", exclude.splitlines())
            config = load_role_config(repo)
            assert config is not None
            self.assertEqual(config.policy_for("implementation").model, "gpt-5.6-sol")
            self.assertEqual(config.policy_for("implementation").speed, "fast")
            self.assertEqual(
                config.policy_for("implementation").reasoning_efforts,
                ("xhigh", "max", "ultra"),
            )
            with self.assertRaisesRegex(RoleConfigError, "already exists"):
                initialize_role_config(repo)
            self.assertEqual(path.read_text(encoding="utf-8"), original)

    def test_role_values_override_defaults_and_omissions_inherit_natively(self) -> None:
        content = VALID_CONFIG.replace(
            "model = gpt-5.6-sol\nspeed = fast",
            "# model and speed intentionally inherit from Codex",
        ).replace(
            "[role.review]\nreasoning_efforts = max, ultra",
            "[role.review]\nmodel = review-model\nspeed = fast\nreasoning_efforts = max",
        )
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            write_config(repo, content)

            config = load_role_config(repo)

        assert config is not None
        self.assertIsNone(config.policy_for("implementation").model)
        self.assertIsNone(config.policy_for("implementation").speed)
        self.assertEqual(config.policy_for("review").model, "review-model")
        self.assertEqual(config.policy_for("review").speed, "fast")
        self.assertEqual(config.policy_for("review").reasoning_efforts, ("max",))

    def test_strict_validation_rejects_invalid_schema_and_values(self) -> None:
        invalid_cases = {
            "default keys": "[DEFAULT]\nmodel = hidden\n\n" + VALID_CONFIG,
            "unknown section": VALID_CONFIG + "\n[role.future]\nreasoning_efforts = max\n",
            "missing role": VALID_CONFIG.replace(
                "\n[role.planning_review]\nreasoning_efforts = max, ultra\n", "\n"
            ),
            "unknown key": VALID_CONFIG.replace(
                "speed = fast", "speed = fast\npriority = fast", 1
            ),
            "bad version": VALID_CONFIG.replace("version = 1", "version = 2"),
            "empty model": VALID_CONFIG.replace("model = gpt-5.6-sol", "model ="),
            "NUL in model": VALID_CONFIG.replace(
                "model = gpt-5.6-sol", "model = gpt-5.6-sol\x00invalid"
            ),
            "bad speed": VALID_CONFIG.replace("speed = fast", "speed = standard"),
            "empty efforts": VALID_CONFIG.replace(
                "reasoning_efforts = xhigh, max, ultra", "reasoning_efforts =", 1
            ),
            "duplicate efforts": VALID_CONFIG.replace(
                "reasoning_efforts = max, ultra", "reasoning_efforts = max, max", 1
            ),
            "unordered efforts": VALID_CONFIG.replace(
                "reasoning_efforts = xhigh, max, ultra",
                "reasoning_efforts = ultra, xhigh",
                1,
            ),
            "unsupported effort": VALID_CONFIG.replace(
                "reasoning_efforts = max, ultra", "reasoning_efforts = extreme", 1
            ),
        }
        for name, content in invalid_cases.items():
            with self.subTest(name=name), tempfile.TemporaryDirectory() as tmp:
                repo = Path(tmp)
                write_config(repo, content)

                with self.assertRaises(RoleConfigError):
                    load_role_config(repo)

    def test_inaccessible_configuration_probe_is_translated(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            init_repo(repo)
            with (
                mock.patch(
                    "scripts.codex_orchestrator.role_config.repository_root",
                    return_value=repo,
                ),
                mock.patch.object(Path, "stat", side_effect=PermissionError("denied")),
            ):
                with self.assertRaisesRegex(RoleConfigError, "could not inspect configuration"):
                    load_role_config(repo)

    def test_manual_policy_accepts_all_sol_efforts_in_canonical_order(self) -> None:
        content = VALID_CONFIG.replace(
            "reasoning_efforts = xhigh, max, ultra",
            "reasoning_efforts = low, medium, high, xhigh, max, ultra",
            1,
        )
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            write_config(repo, content)

            config = load_role_config(repo)

        assert config is not None
        self.assertEqual(
            config.policy_for("implementation").reasoning_efforts,
            ("low", "medium", "high", "xhigh", "max", "ultra"),
        )

    def test_config_commands_report_disabled_and_resolved_settings(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            init_repo(repo)
            disabled = run_cli(
                "config", "show", "--repo", str(repo), "--role", "review", "--json"
            )
            checked = run_cli("config", "check", "--repo", str(repo))
            write_config(repo)
            enabled = run_cli(
                "config", "show", "--repo", str(repo), "--role", "review", "--json"
            )

        self.assertEqual(disabled.returncode, 0, disabled.stderr)
        self.assertFalse(json.loads(disabled.stdout)["enabled"])
        self.assertEqual(checked.returncode, 0, checked.stderr)
        self.assertIn("configuration disabled", checked.stdout)
        self.assertEqual(enabled.returncode, 0, enabled.stderr)
        payload = json.loads(enabled.stdout)
        self.assertEqual(
            payload,
            {
                "enabled": True,
                "model": "gpt-5.6-sol",
                "path": str(repo / CONFIG_RELATIVE_PATH),
                "reasoning_efforts": ["max", "ultra"],
                "role": "review",
                "service_tier": "fast",
                "speed": "fast",
            },
        )

    def test_config_init_cli_requires_git_and_never_overwrites(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            not_git = run_cli("config", "init", "--repo", str(repo))
            init_repo(repo)
            created = run_cli("config", "init", "--repo", str(repo))
            repeated = run_cli("config", "init", "--repo", str(repo))

        self.assertEqual(not_git.returncode, 1)
        self.assertIn("Git worktree", not_git.stderr)
        self.assertEqual(created.returncode, 0, created.stderr)
        self.assertIn("created", created.stdout)
        self.assertEqual(repeated.returncode, 1)
        self.assertIn("already exists", repeated.stderr)

    def test_repository_paths_resolve_from_subdirectories_and_linked_worktrees(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = root / "main"
            linked = root / "linked"
            init_repo(repo)
            subprocess.run(
                [
                    "git",
                    "-C",
                    str(repo),
                    "-c",
                    "user.name=Test",
                    "-c",
                    "user.email=test@example.com",
                    "commit",
                    "--allow-empty",
                    "-qm",
                    "initial",
                ],
                check=True,
            )
            subdirectory = repo / "nested"
            subdirectory.mkdir()

            main_config = initialize_role_config(subdirectory)

            self.assertEqual(main_config, repo / CONFIG_RELATIVE_PATH)
            subprocess.run(
                ["git", "-C", str(repo), "worktree", "add", "-qb", "linked-test", str(linked)],
                check=True,
            )
            linked_config = initialize_role_config(linked)
            ignored = subprocess.run(
                [
                    "git",
                    "-C",
                    str(linked),
                    "check-ignore",
                    "-q",
                    ".codex-orchestrator/config.ini",
                ],
                check=False,
            )

        self.assertEqual(linked_config, linked / CONFIG_RELATIVE_PATH)
        self.assertEqual(ignored.returncode, 0)


if __name__ == "__main__":
    unittest.main()
