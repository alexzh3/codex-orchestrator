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
models = gpt-6.1-sol
speed = default

[role.implementation]
reasoning_efforts = medium, high, xhigh, max, ultra

[role.review]
models = gpt-6.1-sol, gpt-6-astra
reasoning_efforts = high, xhigh, max, ultra

[role.planning]
models = gpt-6-astra
reasoning_efforts = xhigh, max, ultra

[role.planning_review]
models = gpt-6-astra
reasoning_efforts = xhigh, max, ultra
"""
IMPLEMENTATION_EFFORTS = "reasoning_efforts = medium, high, xhigh, max, ultra"
REVIEW_SECTION = (
    "[role.review]\nmodels = gpt-6.1-sol, gpt-6-astra\n"
    "reasoning_efforts = high, xhigh, max, ultra"
)
GENERATED_POLICIES = {
    "implementation": (("gpt-6.1-sol",), ("medium", "high", "xhigh", "max", "ultra")),
    "review": (("gpt-6.1-sol", "gpt-6-astra"), ("high", "xhigh", "max", "ultra")),
    "planning": (("gpt-6-astra",), ("xhigh", "max", "ultra")),
    "planning_review": (("gpt-6-astra",), ("xhigh", "max", "ultra")),
}


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
            for role, (models, efforts) in GENERATED_POLICIES.items():
                with self.subTest(role=role):
                    policy = config.policy_for(role)
                    self.assertEqual(policy.models, models)
                    self.assertEqual(policy.reasoning_efforts, efforts)
                    self.assertEqual(policy.speed, "default")
            with self.assertRaisesRegex(RoleConfigError, "already exists"):
                initialize_role_config(repo)
            self.assertEqual(path.read_text(encoding="utf-8"), original)

    def test_role_values_override_defaults_and_omissions_inherit_natively(self) -> None:
        content = VALID_CONFIG.replace(
            "models = gpt-6.1-sol\nspeed = default",
            "# models and speed intentionally inherit from Codex",
        ).replace(
            REVIEW_SECTION,
            "[role.review]\nmodel = review-model\nspeed = fast\nreasoning_efforts = max",
        )
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            write_config(repo, content)

            config = load_role_config(repo)

        assert config is not None
        self.assertEqual(config.policy_for("implementation").models, ())
        self.assertIsNone(config.policy_for("implementation").speed)
        self.assertEqual(config.policy_for("review").models, ("review-model",))
        self.assertEqual(config.policy_for("planning").models, ("gpt-6-astra",))
        self.assertEqual(config.policy_for("review").speed, "fast")
        self.assertEqual(config.policy_for("review").reasoning_efforts, ("max",))

    def test_role_speed_overrides_default_speed(self) -> None:
        content = VALID_CONFIG.replace(
            "[role.review]\n", "[role.review]\nspeed = fast\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            write_config(repo, content)

            config = load_role_config(repo)

        assert config is not None
        self.assertEqual(config.policy_for("implementation").speed, "default")
        self.assertEqual(config.policy_for("review").speed, "fast")

    def test_strict_validation_rejects_invalid_schema_and_values(self) -> None:
        invalid_cases = {
            "default keys": "[DEFAULT]\nmodel = hidden\n\n" + VALID_CONFIG,
            "unknown section": VALID_CONFIG + "\n[role.future]\nreasoning_efforts = max\n",
            "missing role": VALID_CONFIG.replace(
                "\n[role.planning_review]\nmodels = gpt-6-astra\n"
                "reasoning_efforts = xhigh, max, ultra\n",
                "\n",
            ),
            "unknown key": VALID_CONFIG.replace(
                "speed = default", "speed = default\npriority = fast", 1
            ),
            "bad version": VALID_CONFIG.replace("version = 1", "version = 2"),
            "empty models": VALID_CONFIG.replace("models = gpt-6.1-sol\nspeed", "models =\nspeed"),
            "NUL in models": VALID_CONFIG.replace(
                "models = gpt-6.1-sol\nspeed", "models = gpt-6.1-sol\x00invalid\nspeed"
            ),
            "empty model name": VALID_CONFIG.replace(
                "models = gpt-6.1-sol, gpt-6-astra", "models = gpt-6.1-sol,"
            ),
            "duplicate models": VALID_CONFIG.replace(
                "models = gpt-6.1-sol, gpt-6-astra", "models = gpt-6-astra, gpt-6-astra"
            ),
            "model and models": VALID_CONFIG.replace(
                "models = gpt-6.1-sol\nspeed", "model = gpt-6.1-sol\nmodels = gpt-6.1-sol\nspeed"
            ),
            "list in model": VALID_CONFIG.replace(
                "models = gpt-6.1-sol, gpt-6-astra", "model = gpt-6.1-sol, gpt-6-astra"
            ),
            "bad speed": VALID_CONFIG.replace("speed = default", "speed = standard"),
            "empty efforts": VALID_CONFIG.replace(IMPLEMENTATION_EFFORTS, "reasoning_efforts ="),
            "duplicate efforts": VALID_CONFIG.replace(
                IMPLEMENTATION_EFFORTS, "reasoning_efforts = max, max"
            ),
            "unordered efforts": VALID_CONFIG.replace(
                IMPLEMENTATION_EFFORTS, "reasoning_efforts = ultra, xhigh"
            ),
            "unsupported effort": VALID_CONFIG.replace(
                IMPLEMENTATION_EFFORTS, "reasoning_efforts = extreme"
            ),
        }
        for name, content in invalid_cases.items():
            self.assertNotEqual(content, VALID_CONFIG, name)
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

    def test_manual_policy_accepts_all_efforts_and_keeps_model_order(self) -> None:
        content = VALID_CONFIG.replace(
            IMPLEMENTATION_EFFORTS, "reasoning_efforts = low, medium, high, xhigh, max, ultra"
        ).replace(
            "models = gpt-6.1-sol, gpt-6-astra", "models = gpt-6-astra, gpt-6.1-sol"
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
        self.assertEqual(
            config.policy_for("review").models, ("gpt-6-astra", "gpt-6.1-sol")
        )

    def test_config_commands_report_disabled_and_resolved_settings(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            # resolve(): on macOS the temp dir sits under /var, a symlink to
            # /private/var, while repository_root() reports the resolved path.
            repo = Path(tmp).resolve()
            init_repo(repo)
            disabled = run_cli(
                "config", "show", "--repo", str(repo), "--role", "review", "--json"
            )
            checked = run_cli("config", "check", "--repo", str(repo))
            write_config(repo)
            enabled = run_cli(
                "config", "show", "--repo", str(repo), "--role", "review", "--json"
            )
            planning = run_cli(
                "config", "show", "--repo", str(repo), "--role", "planning", "--json"
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
                "models": ["gpt-6.1-sol", "gpt-6-astra"],
                "path": str(repo / CONFIG_RELATIVE_PATH),
                "reasoning_efforts": ["high", "xhigh", "max", "ultra"],
                "role": "review",
                "service_tier": "default",
                "speed": "default",
            },
        )
        self.assertEqual(planning.returncode, 0, planning.stderr)
        self.assertEqual(json.loads(planning.stdout)["models"], ["gpt-6-astra"])

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
            # resolve(): on macOS the temp dir sits under /var, a symlink to
            # /private/var, while repository_root() reports the resolved path.
            root = Path(tmp).resolve()
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
