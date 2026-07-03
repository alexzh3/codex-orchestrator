from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))


def _write_fake_claude_credentials(home: Path) -> Path:
    """Create a fake ~/.claude/.credentials.json for credentials-mode install tests."""
    claude_dir = home / ".claude"
    claude_dir.mkdir(parents=True, exist_ok=True)
    credentials_file = claude_dir / ".credentials.json"
    credentials_file.write_text(
        '{"claudeAiOauth":{"accessToken":"redacted","refreshToken":"redacted"}}',
        encoding="utf-8",
    )
    return credentials_file


class ExecResult:
    def __init__(
        self,
        return_code: int,
        *,
        stdout: str | None = "",
        stderr: str | None = "",
    ) -> None:
        self.return_code = return_code
        self.stdout = stdout
        self.stderr = stderr


class FakeEnvironment:
    def __init__(self) -> None:
        self.default_user = "agent"
        self.exec_calls: list[dict[str, object]] = []
        self.upload_file_calls: list[tuple[Path | str, str]] = []
        self.upload_dir_calls: list[tuple[Path | str, str]] = []
        self.raise_on_codex_collection = False

    async def exec(
        self,
        command: str,
        cwd: str | None = None,
        env: dict[str, str] | None = None,
        timeout_sec: int | None = None,
        user: str | int | None = None,
    ) -> ExecResult:
        self.exec_calls.append(
            {
                "command": command,
                "cwd": cwd,
                "env": env or {},
                "timeout_sec": timeout_sec,
                "user": user,
            }
        )
        if self.raise_on_codex_collection and "codex-sessions" in command:
            raise RuntimeError("copy failed")
        if "command -v codex" in command:
            return ExecResult(1)
        return ExecResult(0, stdout="ok\n")

    async def upload_file(self, source_path: Path | str, target_path: str) -> None:
        self.upload_file_calls.append((source_path, target_path))

    async def upload_dir(self, source_dir: Path | str, target_dir: str) -> None:
        self.upload_dir_calls.append((source_dir, target_dir))


class HarborAgentTests(unittest.TestCase):
    def test_install_provisions_codex_auth_and_plugin_dir(self) -> None:
        from bench.harbor_agent import CodexOrchestratorAgent

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            home = root / "home"
            auth_dir = home / ".codex"
            auth_dir.mkdir(parents=True)
            auth_file = auth_dir / "auth.json"
            auth_file.write_text('{"OPENAI_API_KEY":"redacted"}', encoding="utf-8")
            _write_fake_claude_credentials(home)
            plugin_dir = root / "plugin"
            plugin_dir.mkdir()
            env = FakeEnvironment()
            agent = CodexOrchestratorAgent(root / "logs")

            with (
                patch("bench.harbor_agent.Path.home", return_value=home),
                patch.dict(
                    os.environ,
                    {
                        "CODEX_FORCE_AUTH_JSON": "1",
                        "CODEX_ORCH_PLUGIN_DIR": str(plugin_dir),
                    },
                    clear=False,
                ),
            ):
                asyncio.run(agent.install(env))

        commands = "\n".join(str(call["command"]) for call in env.exec_calls)
        self.assertIn("npm install -g @openai/codex", commands)
        self.assertIn('ln -sf /tmp/codex-secrets/auth.json "$CODEX_HOME/auth.json"', commands)
        self.assertIn("~/.codex/auth.json", commands)
        self.assertTrue(env.upload_file_calls)
        self.assertEqual(Path(env.upload_file_calls[0][0]), auth_file)
        self.assertEqual(env.upload_file_calls[0][1], "/tmp/codex-secrets/auth.json")
        self.assertEqual(env.upload_dir_calls, [(plugin_dir, "/tmp/codex-orch-plugin")])

    def test_install_provisions_codex_config_toml(self) -> None:
        from bench.harbor_agent import CodexOrchestratorAgent

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            home = root / "home"
            auth_dir = home / ".codex"
            auth_dir.mkdir(parents=True)
            auth_file = auth_dir / "auth.json"
            auth_file.write_text('{"OPENAI_API_KEY":"redacted"}', encoding="utf-8")
            _write_fake_claude_credentials(home)
            plugin_dir = root / "plugin"
            plugin_dir.mkdir()
            env = FakeEnvironment()
            agent = CodexOrchestratorAgent(root / "logs")

            with (
                patch("bench.harbor_agent.Path.home", return_value=home),
                patch.dict(
                    os.environ,
                    {
                        "CODEX_FORCE_AUTH_JSON": "1",
                        "CODEX_ORCH_PLUGIN_DIR": str(plugin_dir),
                    },
                    clear=False,
                ),
            ):
                asyncio.run(agent.install(env))

        commands = "\n".join(str(call["command"]) for call in env.exec_calls)
        self.assertIn('cat >"$CODEX_HOME/config.toml"', commands)
        self.assertIn('model = "gpt-5.5"', commands)
        self.assertIn('model_reasoning_effort = "xhigh"', commands)
        self.assertIn('service_tier = "default"', commands)
        self.assertIn('ln -sf "$CODEX_HOME/config.toml" ~/.codex/config.toml', commands)

    def test_install_provisions_claude_credentials_in_credentials_mode(self) -> None:
        from bench.harbor_agent import CodexOrchestratorAgent

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            home = root / "home"
            auth_dir = home / ".codex"
            auth_dir.mkdir(parents=True)
            (auth_dir / "auth.json").write_text(
                '{"OPENAI_API_KEY":"redacted"}', encoding="utf-8"
            )
            credentials_file = _write_fake_claude_credentials(home)
            plugin_dir = root / "plugin"
            plugin_dir.mkdir()
            env = FakeEnvironment()
            agent = CodexOrchestratorAgent(root / "logs")

            with (
                patch("bench.harbor_agent.Path.home", return_value=home),
                patch.dict(
                    os.environ,
                    {
                        "CODEX_FORCE_AUTH_JSON": "1",
                        "CODEX_ORCH_PLUGIN_DIR": str(plugin_dir),
                    },
                    clear=False,
                ),
            ):
                asyncio.run(agent.install(env))

        # The host credentials file is uploaded verbatim into the container secrets
        # dir, then copied into ~/.claude/.credentials.json with 0600 perms.
        credential_uploads = [
            call for call in env.upload_file_calls if str(call[1]).endswith(".credentials.json")
        ]
        self.assertEqual(len(credential_uploads), 1)
        self.assertEqual(Path(credential_uploads[0][0]), credentials_file)
        self.assertEqual(credential_uploads[0][1], "/tmp/claude-secrets/.credentials.json")
        commands = "\n".join(str(call["command"]) for call in env.exec_calls)
        self.assertIn(
            "cp /tmp/claude-secrets/.credentials.json ~/.claude/.credentials.json",
            commands,
        )
        self.assertIn("chmod 600 ~/.claude/.credentials.json", commands)
        # Secret dir is 0700 and the staging copy is removed after install.
        self.assertIn("chmod 700 ~/.claude /tmp/claude-secrets", commands)
        self.assertIn("rm -f /tmp/claude-secrets/.credentials.json", commands)

    def test_install_skips_claude_credentials_in_token_mode(self) -> None:
        from bench.harbor_agent import CodexOrchestratorAgent

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            home = root / "home"
            auth_dir = home / ".codex"
            auth_dir.mkdir(parents=True)
            (auth_dir / "auth.json").write_text(
                '{"OPENAI_API_KEY":"redacted"}', encoding="utf-8"
            )
            # No ~/.claude/.credentials.json on purpose: token mode must not need it.
            plugin_dir = root / "plugin"
            plugin_dir.mkdir()
            env = FakeEnvironment()
            agent = CodexOrchestratorAgent(root / "logs")

            with (
                patch("bench.harbor_agent.Path.home", return_value=home),
                patch.dict(
                    os.environ,
                    {
                        "CODEX_FORCE_AUTH_JSON": "1",
                        "CODEX_ORCH_PLUGIN_DIR": str(plugin_dir),
                        "CODEX_ORCH_CLAUDE_AUTH_MODE": "token",
                    },
                    clear=False,
                ),
            ):
                asyncio.run(agent.install(env))

        self.assertFalse(
            any(str(call[1]).endswith(".credentials.json") for call in env.upload_file_calls)
        )
        commands = "\n".join(str(call["command"]) for call in env.exec_calls)
        self.assertNotIn(".credentials.json", commands)

    def test_claude_run_uses_plugin_dir_forced_model_effort_and_orchestrate_wrapper(self) -> None:
        from bench.harbor_agent import CodexOrchestratorAgent

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            env = FakeEnvironment()
            agent = CodexOrchestratorAgent(root / "logs", model_name="weaker-model", reasoning_effort="low")
            with patch.dict(
                os.environ,
                {
                    "CLAUDE_FORCE_OAUTH": "1",
                    "CLAUDE_CODE_OAUTH_TOKEN": "token",
                },
                clear=False,
            ):
                asyncio.run(agent.run("Solve the task.", env, object()))

        claude_calls = [
            call for call in env.exec_calls if "claude --verbose" in str(call["command"])
        ]
        self.assertEqual(len(claude_calls), 1)
        command = str(claude_calls[0]["command"])
        command_env = claude_calls[0]["env"]
        self.assertIn("--plugin-dir /tmp/codex-orch-plugin", command)
        self.assertIn("--effort max", command)
        self.assertIn("/codex-orchestrator:orchestrate Solve the task.", command)
        self.assertIsInstance(command_env, dict)
        self.assertEqual(command_env.get("ANTHROPIC_MODEL"), "claude-opus-4-8")
        self.assertEqual(command_env.get("CODEX_HOME"), "/tmp/codex-home")

    def test_run_collects_codex_session_logs_after_claude_run(self) -> None:
        from bench.harbor_agent import CodexOrchestratorAgent

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            env = FakeEnvironment()
            agent = CodexOrchestratorAgent(root / "logs")
            with patch.dict(
                os.environ,
                {
                    "CLAUDE_FORCE_OAUTH": "1",
                    "CLAUDE_CODE_OAUTH_TOKEN": "token",
                },
                clear=False,
            ):
                asyncio.run(agent.run("Solve the task.", env, object()))

        copy_calls = [
            call for call in env.exec_calls if "codex-sessions" in str(call["command"])
        ]
        self.assertEqual(len(copy_calls), 1)
        command = str(copy_calls[0]["command"])
        self.assertIn('cp -a "$CODEX_HOME/sessions/."', command)
        self.assertIn("/logs/agent/codex-sessions", command)
        self.assertIn('find "$CODEX_HOME" -type f -name "*.jsonl"', command)
        self.assertEqual(copy_calls[0]["env"], {"CODEX_HOME": "/tmp/codex-home"})

    def test_run_ignores_codex_session_collection_errors(self) -> None:
        from bench.harbor_agent import CodexOrchestratorAgent

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            env = FakeEnvironment()
            env.raise_on_codex_collection = True
            agent = CodexOrchestratorAgent(root / "logs")
            with patch.dict(
                os.environ,
                {
                    "CLAUDE_FORCE_OAUTH": "1",
                    "CLAUDE_CODE_OAUTH_TOKEN": "token",
                },
                clear=False,
            ):
                asyncio.run(agent.run("Solve the task.", env, object()))

        self.assertTrue(
            any("codex-sessions" in str(call["command"]) for call in env.exec_calls)
        )


class HarborRunnerTests(unittest.TestCase):
    def test_harbor_runner_parses_trial_result_rewards_and_tokens(self) -> None:
        from bench import harbor_runner

        with tempfile.TemporaryDirectory() as tmp:
            trial_dir = Path(tmp) / "jobs" / "job-1" / "trial-1"
            trial_dir.mkdir(parents=True)
            result_path = trial_dir / "result.json"
            result_path.write_text(
                json.dumps(
                    {
                        "task_name": "task-1",
                        "trial_name": "trial-1",
                        "started_at": "2026-07-02T10:00:00",
                        "finished_at": "2026-07-02T10:00:05.500000",
                        "verifier_result": {"rewards": {"reward": 1}},
                        "agent_result": {
                            "n_input_tokens": 100,
                            "n_cache_tokens": 25,
                            "n_output_tokens": 40,
                            "cost_usd": 0.12,
                        },
                    }
                ),
                encoding="utf-8",
            )

            found_path, payload = harbor_runner._find_trial_result(Path(tmp) / "jobs")
            result = harbor_runner._normalize_trial_result(
                payload,
                result_path=found_path,
                measured_wall_seconds=9.0,
            )

        self.assertEqual(found_path, result_path)
        self.assertIs(result["resolved"], True)
        self.assertEqual(result["score"], 1)
        self.assertEqual(result["wall_seconds"], 5.5)
        self.assertEqual(result["raw_result_path"], str(result_path))
        tokens = result["tokens"]
        self.assertIsInstance(tokens, dict)
        self.assertEqual(tokens["input_tokens"], 100)
        self.assertEqual(tokens["output_tokens"], 40)
        self.assertEqual(tokens["cache_read_input_tokens"], 25)
        self.assertEqual(tokens["total_tokens"], 140)
        self.assertEqual(tokens["cost_usd"], 0.12)
        self.assertIsNone(result["gpt_tokens"])
        self.assertEqual(
            result["combined_tokens"],
            {"input_tokens": 100, "output_tokens": 40, "total_tokens": 140},
        )
        self.assertIn("token_note", result)

    def test_harbor_runner_parses_gpt_tokens_from_codex_sessions(self) -> None:
        from bench import harbor_runner

        with tempfile.TemporaryDirectory() as tmp:
            trial_dir = Path(tmp) / "jobs" / "job-1" / "trial-1"
            codex_dir = trial_dir / "agent" / "codex-sessions" / "2026" / "07"
            codex_dir.mkdir(parents=True)
            result_path = trial_dir / "result.json"
            result_path.write_text(
                json.dumps(
                    {
                        "task_name": "task-1",
                        "trial_name": "trial-1",
                        "verifier_result": {"rewards": {"reward": 1}},
                        "agent_result": {
                            "n_input_tokens": 100,
                            "n_output_tokens": 40,
                            "cost_usd": 0.12,
                        },
                    }
                ),
                encoding="utf-8",
            )
            (codex_dir / "rollout-a.jsonl").write_text(
                "\n".join(
                    [
                        "not-json",
                        json.dumps({"type": "thread.started", "thread_id": "session-a"}),
                        json.dumps(
                            {
                                "type": "turn.completed",
                                "thread_id": "session-a",
                                "turn_id": "turn-1",
                                "usage": {"input_tokens": 1000, "output_tokens": 100},
                            }
                        ),
                        json.dumps(
                            {
                                "type": "turn.completed",
                                "thread_id": "session-a",
                                "turn_id": "turn-2",
                                "usage": {
                                    "input_tokens": 1500,
                                    "output_tokens": 250,
                                    "total_tokens": 1750,
                                },
                            }
                        ),
                    ]
                ),
                encoding="utf-8",
            )
            (codex_dir / "rollout-b.jsonl").write_text(
                json.dumps(
                    {
                        "timestamp": "2026-07-02T10:00:00Z",
                        "type": "event_msg",
                        "payload": {
                            "type": "token_count",
                            "info": {
                                "total_token_usage": {
                                    "input_tokens": 2500,
                                    "cached_input_tokens": 1200,
                                    "output_tokens": 400,
                                    "reasoning_output_tokens": 150,
                                    "total_tokens": 2900,
                                },
                                "last_token_usage": {
                                    "input_tokens": 2500,
                                    "cached_input_tokens": 1200,
                                    "output_tokens": 400,
                                    "reasoning_output_tokens": 150,
                                    "total_tokens": 2900,
                                },
                                "model_context_window": 258400,
                            },
                        },
                    }
                ),
                encoding="utf-8",
            )

            found_path, payload = harbor_runner._find_trial_result(Path(tmp) / "jobs")
            result = harbor_runner._normalize_trial_result(
                payload,
                result_path=found_path,
                measured_wall_seconds=1.0,
            )

        self.assertEqual(found_path, result_path)
        self.assertEqual(
            result["gpt_tokens"],
            {
                "input_tokens": 4000,
                "output_tokens": 650,
                "total_tokens": 4650,
                "num_sessions": 2,
                "cost_usd": None,
            },
        )
        self.assertEqual(
            result["combined_tokens"],
            {"input_tokens": 4100, "output_tokens": 690, "total_tokens": 4790},
        )
        self.assertNotIn("token_note", result)

    def test_harbor_runner_missing_codex_sessions_keeps_claude_tokens(self) -> None:
        from bench import harbor_runner

        with tempfile.TemporaryDirectory() as tmp:
            trial_dir = Path(tmp) / "jobs" / "job-1" / "trial-1"
            trial_dir.mkdir(parents=True)
            result_path = trial_dir / "result.json"
            result_path.write_text(
                json.dumps(
                    {
                        "task_name": "task-1",
                        "trial_name": "trial-1",
                        "verifier_result": {"rewards": {"reward": 1}},
                        "agent_result": {
                            "n_input_tokens": 12,
                            "n_output_tokens": 8,
                        },
                    }
                ),
                encoding="utf-8",
            )

            found_path, payload = harbor_runner._find_trial_result(Path(tmp) / "jobs")
            result = harbor_runner._normalize_trial_result(
                payload,
                result_path=found_path,
                measured_wall_seconds=1.0,
            )

        self.assertIsNone(result["gpt_tokens"])
        self.assertEqual(
            result["combined_tokens"],
            {"input_tokens": 12, "output_tokens": 8, "total_tokens": 20},
        )
        self.assertIn("token_note", result)

    def test_harbor_runner_detects_codex_exec_dispatches_in_claude_trajectory(self) -> None:
        from bench import harbor_runner

        with tempfile.TemporaryDirectory() as tmp:
            trial_dir = Path(tmp) / "jobs" / "job-1" / "trial-1"
            agent_dir = trial_dir / "agent"
            agent_dir.mkdir(parents=True)
            result_path = trial_dir / "result.json"
            result_path.write_text(
                json.dumps(
                    {
                        "task_name": "task-1",
                        "trial_name": "trial-1",
                        "verifier_result": {"rewards": {"reward": 1}},
                    }
                ),
                encoding="utf-8",
            )
            (agent_dir / "claude-code.txt").write_text(
                "\n".join(
                    [
                        "non-json status line",
                        json.dumps(
                            {
                                "type": "assistant",
                                "message": {
                                    "content": [
                                        {
                                            "type": "tool_use",
                                            "name": "Bash",
                                            "input": {
                                                "command": "codex exec --json - < prompt.md"
                                            },
                                        }
                                    ]
                                },
                            }
                        ),
                    ]
                ),
                encoding="utf-8",
            )

            found_path, payload = harbor_runner._find_trial_result(Path(tmp) / "jobs")
            result = harbor_runner._normalize_trial_result(
                payload,
                result_path=found_path,
                measured_wall_seconds=1.0,
            )

        self.assertEqual(found_path, result_path)
        self.assertGreaterEqual(result["codex_sessions_spawned"], 1)
        self.assertIs(result["real_orchestration"], True)
        self.assertIsNone(result["orchestration_note"])

    def test_harbor_runner_flags_trajectory_without_codex_exec_as_degenerate(self) -> None:
        from bench import harbor_runner

        with tempfile.TemporaryDirectory() as tmp:
            trial_dir = Path(tmp) / "jobs" / "job-1" / "trial-1"
            agent_dir = trial_dir / "agent"
            agent_dir.mkdir(parents=True)
            result_path = trial_dir / "result.json"
            result_path.write_text(
                json.dumps(
                    {
                        "task_name": "task-1",
                        "trial_name": "trial-1",
                        "verifier_result": {"rewards": {"reward": 1}},
                    }
                ),
                encoding="utf-8",
            )
            (agent_dir / "claude-code.txt").write_text(
                json.dumps(
                    {
                        "type": "assistant",
                        "message": {
                            "content": [
                                {
                                    "type": "tool_use",
                                    "name": "Bash",
                                    "input": {"command": "python3 solve.py"},
                                }
                            ]
                        },
                    }
                ),
                encoding="utf-8",
            )

            found_path, payload = harbor_runner._find_trial_result(Path(tmp) / "jobs")
            result = harbor_runner._normalize_trial_result(
                payload,
                result_path=found_path,
                measured_wall_seconds=1.0,
            )

        self.assertEqual(result["codex_sessions_spawned"], 0)
        self.assertIs(result["real_orchestration"], False)
        self.assertIsNone(result["orchestration_note"])

    def test_resolve_harbor_env_credentials_mode_needs_no_token(self) -> None:
        from bench import harbor_runner

        with patch.dict(
            os.environ,
            {"CODEX_ORCH_CLAUDE_AUTH_MODE": "credentials"},
            clear=False,
        ):
            os.environ.pop("CLAUDE_CODE_OAUTH_TOKEN", None)
            env_values = harbor_runner._resolve_harbor_env(
                Path("/tmp/plugin"), "CLAUDE_CODE_OAUTH_TOKEN"
            )

        self.assertEqual(env_values["CODEX_ORCH_CLAUDE_AUTH_MODE"], "credentials")
        self.assertEqual(env_values["CODEX_ORCH_PLUGIN_DIR"], "/tmp/plugin")
        self.assertEqual(env_values["CODEX_FORCE_AUTH_JSON"], "1")
        # Subscription credentials file wins over any stray API key, and a stale
        # inherited host OAuth token must be cleared so it cannot reach Claude.
        self.assertEqual(env_values["ANTHROPIC_API_KEY"], "")
        self.assertEqual(env_values["CLAUDE_CODE_OAUTH_TOKEN"], "")
        # "0", not "" — Harbor parses CLAUDE_FORCE_OAUTH as a bool and rejects "".
        self.assertEqual(env_values["CLAUDE_FORCE_OAUTH"], "0")

    def test_resolve_harbor_env_token_mode_requires_token(self) -> None:
        from bench import harbor_runner

        with patch.dict(
            os.environ,
            {"CODEX_ORCH_CLAUDE_AUTH_MODE": "token"},
            clear=False,
        ):
            os.environ.pop("CLAUDE_CODE_OAUTH_TOKEN", None)
            with self.assertRaises(RuntimeError) as missing_token:
                harbor_runner._resolve_harbor_env(
                    Path("/tmp/plugin"), "CLAUDE_CODE_OAUTH_TOKEN"
                )

            with patch.dict(
                os.environ, {"CLAUDE_CODE_OAUTH_TOKEN": "secret-token"}, clear=False
            ):
                env_values = harbor_runner._resolve_harbor_env(
                    Path("/tmp/plugin"), "CLAUDE_CODE_OAUTH_TOKEN"
                )

        self.assertIn("CLAUDE_CODE_OAUTH_TOKEN", str(missing_token.exception))
        self.assertEqual(env_values["CLAUDE_FORCE_OAUTH"], "1")
        self.assertEqual(env_values["CLAUDE_CODE_OAUTH_TOKEN"], "secret-token")
        self.assertNotIn("ANTHROPIC_API_KEY", env_values)

    def test_verify_result_identity_rejects_mismatched_task(self) -> None:
        from bench import harbor_runner

        with self.assertRaises(RuntimeError) as mismatch:
            harbor_runner._verify_result_identity(
                {"task_name": "some-other-task"}, "book-portfolio-analysis", Path("/x/result.json")
            )
        self.assertIn("some-other-task", str(mismatch.exception))
        # Matching (or substring) identity passes without raising.
        harbor_runner._verify_result_identity(
            {"task_name": "book-portfolio-analysis"}, "book-portfolio-analysis", Path("/x")
        )

    def test_verifier_rewards_requires_rewards_object(self) -> None:
        from bench import harbor_runner

        with self.assertRaises(RuntimeError) as legacy:
            harbor_runner._verifier_rewards({"verifier_result": {"reward": 1}})
        self.assertIn("rewards", str(legacy.exception))
        self.assertEqual(
            harbor_runner._verifier_rewards({"verifier_result": {"rewards": {"reward": 1}}}),
            {"reward": 1},
        )

    def test_harbor_runner_imports_without_harbor_and_raises_clear_runtime_error(self) -> None:
        from bench import harbor_runner
        from bench.adapters.tblite import TBLiteAdapter

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plugin_dir = root / "plugin"
            plugin_dir.mkdir()
            jobs_dir = root / "jobs"
            with (
                patch.dict(os.environ, {"CLAUDE_CODE_OAUTH_TOKEN": "token"}, clear=False),
                patch("importlib.util.find_spec", return_value=None),
                patch("shutil.which", return_value=None),
            ):
                with self.assertRaises(RuntimeError) as runner_error:
                    harbor_runner.run_tblite_task_via_harbor(
                        "task-1",
                        plugin_dir,
                        dataset="openthoughts-tblite",
                        model="ignored",
                        effort="ignored",
                        jobs_dir=jobs_dir,
                        oauth_token_env="CLAUDE_CODE_OAUTH_TOKEN",
                        timeout=1,
                    )

                adapter = TBLiteAdapter()
                with self.assertRaises(RuntimeError) as adapter_error:
                    adapter.run_task(
                        {
                            "id": "task-1",
                            "prompt": "Solve it.",
                            "selection": "lowest_success_rate",
                        },
                        str(plugin_dir),
                        dry_run=False,
                        repo_root=ROOT,
                        work_dir=root / "work",
                    )

        self.assertIn("Harbor is not installed", str(runner_error.exception))
        self.assertIn("Harbor is not installed", str(adapter_error.exception))

    def test_tblite_real_result_exposes_token_breakdown(self) -> None:
        from bench.adapters.tblite import TBLiteAdapter
        from codex_orch import validate_benchmark_result

        claude_tokens = {
            "input_tokens": 100,
            "output_tokens": 50,
            "cache_read_input_tokens": 10,
            "cache_creation_input_tokens": None,
            "total_tokens": 150,
            "cost_usd": 0.2,
            "num_turns_reported": None,
        }
        gpt_tokens = {
            "input_tokens": 25,
            "output_tokens": 7,
            "total_tokens": 32,
            "num_sessions": 2,
            "cost_usd": None,
        }
        combined_tokens = {
            "input_tokens": 125,
            "output_tokens": 57,
            "total_tokens": 182,
        }
        harbor_result = {
            "resolved": True,
            "verifier_exit": 0,
            "score": 1,
            "wall_seconds": 2.5,
            "tokens": claude_tokens,
            "claude_tokens": claude_tokens,
            "gpt_tokens": gpt_tokens,
            "combined_tokens": combined_tokens,
            "raw_result_path": "/tmp/result.json",
            "verifier_rewards": {"reward": 1},
            "exception": None,
            "codex_sessions_spawned": 2,
            "real_orchestration": True,
            "orchestration_note": None,
        }

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plugin_dir = root / "plugin"
            plugin_dir.mkdir()
            adapter = TBLiteAdapter()
            with patch("bench.harbor_runner.run_tblite_task_via_harbor", return_value=harbor_result):
                result = adapter.run_task(
                    {
                        "id": "task-1",
                        "prompt": "Solve it.",
                        "selection": "lowest_success_rate",
                    },
                    str(plugin_dir),
                    dry_run=False,
                    repo_root=ROOT,
                    work_dir=root / "work",
                )

        validate_benchmark_result(result)
        self.assertEqual(result["token_usage"], claude_tokens)
        self.assertEqual(result["codex_sessions"], 2)
        external_score = result["external_score"]
        self.assertIsInstance(external_score, dict)
        self.assertEqual(external_score["codex_sessions_spawned"], 2)
        self.assertIs(external_score["real_orchestration"], True)
        self.assertEqual(
            external_score["token_breakdown"],
            {
                "claude": {
                    "input_tokens": 100,
                    "output_tokens": 50,
                    "total_tokens": 150,
                    "cost_usd": 0.2,
                },
                "gpt": {
                    "input_tokens": 25,
                    "output_tokens": 7,
                    "total_tokens": 32,
                    "num_sessions": 2,
                    "cost_usd": None,
                },
                "combined": {
                    "input_tokens": 125,
                    "output_tokens": 57,
                    "total_tokens": 182,
                },
            },
        )


if __name__ == "__main__":
    unittest.main()
