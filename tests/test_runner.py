from __future__ import annotations

import contextlib
import io
import json
import os
import signal
import subprocess
import sys
import tempfile
import textwrap
import time
import unittest
from pathlib import Path
from unittest import mock

from scripts.codex_orchestrator import runner
from scripts.codex_orchestrator.role_config import RoleConfigError, RolePolicy
from scripts.codex_orchestrator.runner import EventRenderer, sanitize_text

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "codex_orch_tools.py"
VALID_ROLE_CONFIG = (
    "[meta]\nversion=1\n[defaults]\nmodel=gpt-5.6-sol\nspeed=fast\n"
    "[role.implementation]\nreasoning_efforts=xhigh,max,ultra\n"
    "[role.review]\nreasoning_efforts=max,ultra\n"
    "[role.planning]\nreasoning_efforts=max,ultra\n"
    "[role.planning_review]\nreasoning_efforts=max,ultra\n"
)


def render(renderer: EventRenderer, event: object) -> list[str]:
    return renderer.render(json.dumps(event, separators=(",", ":")))


def run_child(
    root: Path,
    code: str,
    *,
    prompt: bytes = b"prompt bytes\n",
    child_args: tuple[str, ...] = (),
    events: Path | None = None,
    timeout: float | None = None,
    run_args: tuple[str, ...] = (),
) -> tuple[subprocess.CompletedProcess[str], Path]:
    prompt_path = root / "prompt.md"
    prompt_path.write_bytes(prompt)
    events_path = root / "events.jsonl" if events is None else events
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "run",
            "--label",
            "test-agent",
            "--events",
            str(events_path),
            "--prompt",
            str(prompt_path),
            *run_args,
            "--",
            sys.executable,
            "-c",
            code,
            *child_args,
        ],
        check=False,
        text=True,
        capture_output=True,
        cwd=ROOT,
        timeout=timeout,
    )
    return result, events_path


class EventRendererTests(unittest.TestCase):
    def test_supported_event_families_render_compact_messages(self) -> None:
        renderer = EventRenderer()

        self.assertEqual(
            render(renderer, {"type": "thread.started", "thread_id": "thread-1"}),
            ["thread started thread-1"],
        )
        self.assertEqual(render(renderer, {"type": "turn.started"}), ["turn started"])
        self.assertEqual(
            render(
                renderer,
                {
                    "type": "turn.completed",
                    "usage": {
                        "input_tokens": 10,
                        "cached_input_tokens": 6,
                        "output_tokens": 4,
                        "reasoning_output_tokens": 2,
                    },
                },
            ),
            ["turn completed input=10 cached=6 output=4"],
        )
        self.assertEqual(
            render(renderer, {"type": "turn.completed", "usage": {"output_tokens": 3}}),
            ["turn completed output=3"],
        )
        self.assertEqual(
            render(renderer, {"type": "turn.failed", "error": "bad request"}),
            ["turn failed: bad request"],
        )
        self.assertEqual(
            render(renderer, {"type": "error", "message": "authentication failed"}),
            ["error: authentication failed"],
        )
        self.assertEqual(
            render(renderer, {"type": "error", "message": "Reconnecting to stream"}),
            ["warning: Reconnecting to stream"],
        )

        command = {
            "id": "cmd-1",
            "type": "command_execution",
            "command": "python -m unittest",
            "aggregated_output": "in-progress output MUST_NOT_RENDER",
            "status": "in_progress",
            "exit_code": None,
        }
        self.assertEqual(
            render(renderer, {"type": "item.started", "item": command}),
            ["python -m unittest"],
        )
        self.assertEqual(render(renderer, {"type": "item.updated", "item": command}), [])
        command["status"] = "completed"
        command["exit_code"] = 0
        command["aggregated_output"] = "Ran 12 tests\n\nOK\n"
        self.assertEqual(
            render(renderer, {"type": "item.completed", "item": command}),
            ["Ran 12 tests", "", "OK"],
        )
        command["status"] = "failed"
        command["exit_code"] = None
        command["aggregated_output"] = ""
        self.assertEqual(
            render(renderer, {"type": "item.completed", "item": command}),
            [],
        )
        del command["aggregated_output"]
        self.assertEqual(
            render(renderer, {"type": "item.completed", "item": command}),
            [],
        )
        command["aggregated_output"] = {"unexpected": "shape"}
        self.assertEqual(
            render(renderer, {"type": "item.completed", "item": command}),
            [],
        )

        command["aggregated_output"] = (
            "\x1b[31mfailed\x1b[0m\n--token\nSENSITIVE\n" + "x" * 200
        )
        output = render(renderer, {"type": "item.completed", "item": command})
        self.assertEqual(output[:2], ["failed", "--token [redacted]"])
        self.assertEqual(len(output[2]), 160)
        self.assertTrue(output[2].endswith("..."))

        changes = [
            {"kind": "update", "path": f"path-{index}.py"} for index in range(1, 8)
        ]
        file_item = {"id": "files-1", "type": "file_change", "changes": changes}
        self.assertEqual(
            render(renderer, {"type": "item.started", "item": file_item}), []
        )
        file_message = render(renderer, {"type": "item.completed", "item": file_item})
        self.assertEqual(
            file_message,
            [
                "files completed: update path-1.py, update path-2.py, update path-3.py, "
                "update path-4.py, update path-5.py, +2 more"
            ],
        )
        self.assertNotIn("path-6.py", file_message[0])

        long_changes = [
            {"kind": "update", "path": f"path-{index}-{'x' * 100}.py"}
            for index in range(1, 8)
        ]
        long_file_item = {
            "id": "files-2",
            "type": "file_change",
            "changes": long_changes,
        }
        long_message = render(
            renderer, {"type": "item.completed", "item": long_file_item}
        )[0]
        self.assertTrue(long_message.endswith(", +2 more"), long_message)

        mcp_item = {
            "id": "mcp-1",
            "type": "mcp_tool_call",
            "server": "github",
            "tool": "get_pr",
            "status": "in_progress",
        }
        self.assertEqual(
            render(renderer, {"type": "item.started", "item": mcp_item}),
            ["mcp started: github.get_pr"],
        )
        mcp_item["status"] = "completed"
        self.assertEqual(
            render(renderer, {"type": "item.completed", "item": mcp_item}),
            ["mcp completed: github.get_pr status=completed"],
        )

        web_item = {"id": "web-1", "type": "web_search", "query": "Codex CLI"}
        self.assertEqual(render(renderer, {"type": "item.started", "item": web_item}), [])
        self.assertEqual(
            render(renderer, {"type": "item.completed", "item": web_item}),
            ["web search: Codex CLI"],
        )

        item_error = {"id": "err-1", "type": "error", "message": "tool unavailable"}
        self.assertEqual(
            render(renderer, {"type": "item.completed", "item": item_error}),
            ["warning: tool unavailable"],
        )

        for item_type in ("reasoning", "agent_message"):
            hidden = {"id": item_type, "type": item_type, "text": "MUST_NOT_RENDER"}
            self.assertEqual(
                render(renderer, {"type": "item.completed", "item": hidden}), []
            )

    def test_todo_transitions_and_duplicate_completion_are_suppressed(self) -> None:
        renderer = EventRenderer()
        initial = {
            "id": "todo-1",
            "type": "todo_list",
            "items": [
                {"text": "Write code", "completed": False},
                {"text": "Run tests", "completed": False},
            ],
        }
        self.assertEqual(
            render(renderer, {"type": "item.started", "item": initial}),
            ["todo plan: 2 items"],
        )

        updated = json.loads(json.dumps(initial))
        updated["items"][0]["completed"] = True
        self.assertEqual(
            render(renderer, {"type": "item.updated", "item": updated}),
            ["todo done: Write code"],
        )
        self.assertEqual(
            render(renderer, {"type": "item.completed", "item": updated}), []
        )

        changed = json.loads(json.dumps(updated))
        changed["items"].append({"text": "Ship", "completed": False})
        self.assertEqual(
            render(renderer, {"type": "item.updated", "item": changed}),
            ["todo plan: 3 items"],
        )
        changed["items"][0]["completed"] = False
        self.assertEqual(render(renderer, {"type": "item.updated", "item": changed}), [])
        changed["items"][0]["completed"] = True
        self.assertEqual(render(renderer, {"type": "item.updated", "item": changed}), [])

    def test_sanitization_removes_ansi_collapses_redacts_and_is_ascii(self) -> None:
        value = sanitize_text(
            " \x1b[31mhello\x1b[0m\n world  Bearer abc123 "
            "access_token=tok password: 'two words' api_key=key authorization:Bearer z \N{SNOWMAN} "
        )

        self.assertEqual(
            value,
            "hello world Bearer [redacted] access_token=[redacted] password:[redacted] "
            "api_key=[redacted] authorization:[redacted] \\u2603",
        )
        value.encode("ascii")

    def test_sanitization_truncates_to_160_characters(self) -> None:
        value = sanitize_text("x" * 200)

        self.assertEqual(len(value), 160)
        self.assertTrue(value.endswith("..."))

    def test_sanitization_redacts_space_separated_secret_flags(self) -> None:
        value = sanitize_text(
            "tool --token SENSITIVE_VALUE --password 'ALSO SENSITIVE' "
            "--api-key API_VALUE authorization Bearer auth-token "
            "token-file credentials.txt deploy"
        )

        self.assertEqual(
            value,
            "tool --token [redacted] --password [redacted] --api-key [redacted] "
            "authorization [redacted] token-file [redacted] deploy",
        )

    def test_scrubbing_is_idempotent_for_hostile_inputs(self) -> None:
        hostile_inputs = (
            "access_token=tok",
            "agent --token SENSITIVE_VALUE",
            "authorization Bearer sensitive-value",
            'password="two words" secret:\'escaped value\'',
            "\x1b[31mapi_key=key\x1b[0m",
            "agent --token\x07SENSITIVE_VALUE\x00tail",
            "Bearer non-ascii-\N{SNOWMAN}",
            "prefix " + "x" * 1_000 + " token=last",
        )

        for value in hostile_inputs:
            with self.subTest(value=value):
                scrubbed = runner.scrub_text(value)
                self.assertEqual(runner.scrub_text(scrubbed), scrubbed)

    def test_control_characters_cannot_hide_secret_separators(self) -> None:
        self.assertEqual(
            sanitize_text("agent --token\x07SENSITIVE_VALUE"),
            "agent --token [redacted]",
        )

    def test_unknown_types_and_unparseable_lines_warn_only_once(self) -> None:
        renderer = EventRenderer()

        self.assertEqual(
            render(renderer, {"type": "future.event"}),
            ["warning: unknown event type future.event"],
        )
        self.assertEqual(render(renderer, {"type": "future.event"}), [])
        self.assertEqual(
            render(renderer, {"type": "another.event"}),
            ["warning: unknown event type another.event"],
        )
        unknown_item = {"type": "future_item", "id": "one"}
        self.assertEqual(
            render(renderer, {"type": "item.started", "item": unknown_item}),
            ["warning: unknown item type future_item"],
        )
        self.assertEqual(
            render(renderer, {"type": "item.completed", "item": unknown_item}), []
        )
        self.assertEqual(renderer.render("not json"), ["warning: unparseable event line"])
        self.assertEqual(renderer.render("still not json"), [])
        self.assertEqual(renderer.render("\n"), [])


class RunnerProcessTests(unittest.TestCase):
    def test_events_are_preserved_byte_for_byte(self) -> None:
        raw = (
            b'{"type":"turn.started"}\n'
            b'{"type":"turn.started","detail":"\xff invalid utf8"}\n'
            b'{"type":"item.completed","item":{"type":"reasoning","text":"hidden"}}\n'
            b"unterminated final line"
        )
        code = f"import sys; sys.stdout.buffer.write({raw!r}); sys.stdout.buffer.flush()"
        with tempfile.TemporaryDirectory() as tmp:
            result, events = run_child(Path(tmp), code)
            captured = events.read_bytes()

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(captured, raw)
        self.assertEqual(result.stdout.count("warning: unparseable event line"), 1)
        self.assertRegex(
            result.stdout.splitlines()[-1], r"^\d\d:\d\d:\d\d exited code=0$"
        )
        self.assertNotIn("test-agent", result.stdout)
        self.assertNotIn("hidden", result.stdout)

    def test_command_display_has_command_and_final_output_without_synthetic_labels(
        self,
    ) -> None:
        records = [
            {"type": "thread.started", "thread_id": "abc123"},
            {"type": "turn.started"},
            {
                "type": "item.started",
                "item": {
                    "id": "cmd-1",
                    "type": "command_execution",
                    "command": "python -m unittest",
                    "aggregated_output": "",
                    "status": "in_progress",
                },
            },
            {
                "type": "item.updated",
                "item": {
                    "id": "cmd-1",
                    "type": "command_execution",
                    "command": "python -m unittest",
                    "aggregated_output": "partial output MUST_NOT_RENDER",
                    "status": "in_progress",
                },
            },
            {
                "type": "item.completed",
                "item": {
                    "id": "cmd-1",
                    "type": "command_execution",
                    "command": "python -m unittest",
                    "aggregated_output": "Ran 12 tests\nOK\n",
                    "status": "completed",
                    "exit_code": 0,
                },
            },
            {"type": "turn.completed", "usage": {"output_tokens": 4}},
        ]
        raw = "".join(json.dumps(record) + "\n" for record in records).encode()
        code = f"import sys; sys.stdout.buffer.write({raw!r}); sys.stdout.buffer.flush()"

        with tempfile.TemporaryDirectory() as tmp:
            result, events = run_child(Path(tmp), code)
            captured = events.read_bytes()

        messages = [line[9:] for line in result.stdout.splitlines()]
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(captured, raw)
        self.assertEqual(
            messages,
            [
                "thread started abc123",
                "turn started",
                "python -m unittest",
                "Ran 12 tests",
                "OK",
                "turn completed output=4",
                "exited code=0",
            ],
        )
        self.assertNotIn("test-agent", result.stdout)
        self.assertNotIn("command started", result.stdout)
        self.assertNotIn("command completed", result.stdout)
        self.assertNotIn("MUST_NOT_RENDER", result.stdout)

    def test_hostile_integer_line_does_not_interrupt_capture(self) -> None:
        hostile = b'{"type":"turn.started","n":' + (b"9" * 5_000) + b"}\n"
        completed = b'{"type":"turn.completed","usage":{"output_tokens":1}}\n'
        raw = hostile + completed
        code = f"import sys; sys.stdout.buffer.write({raw!r}); sys.stdout.buffer.flush()"
        with tempfile.TemporaryDirectory() as tmp:
            result, events = run_child(Path(tmp), code, timeout=5)
            captured = events.read_bytes()

        warnings = [line for line in result.stdout.splitlines() if " warning:" in line]
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(captured, raw)
        self.assertEqual(len(warnings), 1, result.stdout)
        self.assertNotIn("Traceback", result.stderr)

    def test_unexpected_renderer_failure_is_isolated(self) -> None:
        raw = b'{"type":"turn.started"}\n{"type":"turn.completed"}\n'
        code = f"import sys; sys.stdout.buffer.write({raw!r}); sys.stdout.buffer.flush()"
        events = io.BytesIO()
        stdout = io.StringIO()
        stderr = io.StringIO()

        with (
            contextlib.redirect_stdout(stdout),
            contextlib.redirect_stderr(stderr),
            mock.patch.object(
                runner.EventRenderer,
                "render_bytes",
                side_effect=RuntimeError("renderer failed"),
            ) as render_bytes,
        ):
            result = runner._run_child(
                [sys.executable, "-c", code], b"", events, "test-agent", time.monotonic()
            )

        warnings = [line for line in stdout.getvalue().splitlines() if " warning:" in line]
        self.assertEqual(result, 0, stderr.getvalue())
        self.assertEqual(events.getvalue(), raw)
        self.assertEqual(len(warnings), 1, stdout.getvalue())
        self.assertEqual(render_bytes.call_count, 1)
        self.assertNotIn("exited code=", stdout.getvalue())
        self.assertNotIn("Traceback", stderr.getvalue())

    def test_prompt_bytes_are_delivered_exactly(self) -> None:
        prompt = b"\x00\xfffirst\r\nsecond without newline"
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            echoed = root / "stdin.bin"
            code = (
                "import pathlib,sys; "
                "pathlib.Path(sys.argv[1]).write_bytes(sys.stdin.buffer.read())"
            )
            result, _ = run_child(root, code, prompt=prompt, child_args=(str(echoed),))
            delivered = echoed.read_bytes()

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(delivered, prompt)

    def test_large_prompt_does_not_deadlock_before_child_output(self) -> None:
        prompt = b"p" * (1024 * 1024)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            delivered_path = root / "large-prompt.bin"
            code = (
                "import pathlib,sys; "
                "pathlib.Path(sys.argv[1]).write_bytes(sys.stdin.buffer.read())"
            )
            result, _ = run_child(
                root,
                code,
                prompt=prompt,
                child_args=(str(delivered_path),),
                timeout=10,
            )
            delivered = delivered_path.read_bytes()

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(delivered, prompt)

    def test_undelivered_large_prompt_is_an_error(self) -> None:
        prompt = b"p" * (1024 * 1024)
        with tempfile.TemporaryDirectory() as tmp:
            result, events = run_child(
                Path(tmp),
                "raise SystemExit(0)",
                prompt=prompt,
                timeout=5,
            )

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("could not write child stdin", result.stderr)
            self.assertTrue(events.exists())
            self.assertEqual(events.read_bytes(), b"")

    def test_child_receives_all_arguments_after_separator(self) -> None:
        forwarded = ("--json", "-", "resume", "--", "literal", "--more")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            argv_path = root / "argv.json"
            code = (
                "import json,pathlib,sys; "
                "pathlib.Path(sys.argv[1]).write_text(json.dumps(sys.argv[2:]))"
            )
            result, _ = run_child(
                root,
                code,
                child_args=(str(argv_path), *forwarded),
            )
            received = json.loads(argv_path.read_text(encoding="utf-8"))

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(received, list(forwarded))

    def test_missing_role_config_preserves_child_arguments_and_creates_nothing(self) -> None:
        forwarded = ("--json", "-", "resume", "--", "literal", "--more")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            subprocess.run(["git", "init", "-q", str(root)], check=True)
            argv_path = root / "argv.json"
            code = (
                "import json,pathlib,sys; "
                "pathlib.Path(sys.argv[1]).write_text(json.dumps(sys.argv[2:]))"
            )
            result, _ = run_child(
                root,
                code,
                child_args=(str(argv_path), *forwarded),
                run_args=("--repo", str(root), "--role", "implementation"),
            )
            received = json.loads(argv_path.read_text(encoding="utf-8"))

            self.assertFalse((root / ".codex-orchestrator").exists())

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(received, list(forwarded))

    def test_configured_command_injects_exact_fresh_and_resume_arguments(self) -> None:
        policy = RolePolicy(
            model="gpt-5.6-sol",
            speed="fast",
            reasoning_efforts=("xhigh", "max", "ultra"),
        )
        injected = [
            "--model",
            "gpt-5.6-sol",
            "-c",
            'model_reasoning_effort="max"',
            "-c",
            'service_tier="fast"',
            "--enable",
            "fast_mode",
        ]

        fresh = runner._configured_command(
            ["codex", "exec", "-C", "/work", "--json", "-"], policy, "max"
        )
        resumed = runner._configured_command(
            ["/usr/bin/codex", "exec", "-C", "/work", "resume", "--json", "id", "-"],
            policy,
            "max",
        )

        self.assertEqual(
            fresh, ["codex", "exec", *injected, "-C", "/work", "--json", "-"]
        )
        self.assertEqual(
            resumed,
            [
                "/usr/bin/codex",
                "exec",
                *injected,
                "-C",
                "/work",
                "resume",
                "--json",
                "id",
                "-",
            ],
        )

    def test_active_config_injects_once_and_propagates_child_failure(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            subprocess.run(["git", "init", "-q", str(root)], check=True)
            config = root / ".codex-orchestrator" / "config.ini"
            config.parent.mkdir()
            config.write_text(VALID_ROLE_CONFIG, encoding="utf-8")
            prompt = root / "prompt.md"
            events = root / "events.jsonl"
            invocations = root / "invocations.json"
            fake_codex = root / "codex"
            prompt.write_text("review this", encoding="utf-8")
            fake_codex.write_text(
                textwrap.dedent(
                    f"""\
                    #!{sys.executable}
                    import json
                    import pathlib
                    import sys

                    path = pathlib.Path({str(invocations)!r})
                    previous = json.loads(path.read_text()) if path.exists() else []
                    path.write_text(json.dumps([*previous, sys.argv[1:]]))
                    sys.stdin.buffer.read()
                    sys.stderr.write("Fast tier entitlement denied\\n")
                    raise SystemExit(7)
                    """
                ),
                encoding="utf-8",
            )
            fake_codex.chmod(0o755)

            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "run",
                    "--repo",
                    str(root),
                    "--role",
                    "review",
                    "--reasoning-effort",
                    "ultra",
                    "--events",
                    str(events),
                    "--prompt",
                    str(prompt),
                    "--",
                    str(fake_codex),
                    "exec",
                    "--json",
                    "-",
                ],
                check=False,
                text=True,
                capture_output=True,
                cwd=ROOT,
            )
            received = json.loads(invocations.read_text(encoding="utf-8"))
            captured_events = events.read_bytes()

        self.assertEqual(result.returncode, 7, result.stderr)
        self.assertEqual(result.stderr, "Fast tier entitlement denied\n")
        self.assertEqual(
            received,
            [
                [
                    "exec",
                    "--model",
                    "gpt-5.6-sol",
                    "-c",
                    'model_reasoning_effort="ultra"',
                    "-c",
                    'service_tier="fast"',
                    "--enable",
                    "fast_mode",
                    "--json",
                    "-",
                ]
            ],
        )
        self.assertEqual(captured_events, b"")

    def test_configured_default_speed_forces_default_service_tier(self) -> None:
        policy = RolePolicy(model=None, speed="default", reasoning_efforts=("max",))

        command = runner._configured_command(["codex", "exec", "--json", "-"], policy, "max")

        self.assertEqual(
            command,
            [
                "codex",
                "exec",
                "-c",
                'model_reasoning_effort="max"',
                "-c",
                'service_tier="default"',
                "--json",
                "-",
            ],
        )
        self.assertNotIn("fast_mode", command)

    def test_configured_command_rejects_disallowed_effort_and_non_codex_child(self) -> None:
        policy = RolePolicy(model=None, speed=None, reasoning_efforts=("max", "ultra"))

        with self.assertRaisesRegex(RoleConfigError, "not allowed"):
            runner._configured_command(["codex", "exec", "-"], policy, "xhigh")
        with self.assertRaisesRegex(RoleConfigError, "codex exec"):
            runner._configured_command([sys.executable, "-c", "pass"], policy, "max")

    def test_configured_command_rejects_performance_conflicts(self) -> None:
        policy = RolePolicy(model="model", speed="fast", reasoning_efforts=("max",))
        conflicts = (
            ("-m", "other"),
            ("-m=other",),
            ("-mother",),
            ("--model", "other"),
            ("--model=other",),
            ("-c", 'model="other"'),
            ("--config", 'model_reasoning_effort="ultra"'),
            ("--config=service_tier=standard",),
            ("-cfeatures.fast_mode=false",),
            ("--enable", "fast_mode"),
            ("--disable", "fast_mode"),
            ("--enable=fast_mode",),
            ("--disable=fast_mode",),
        )
        for conflict in conflicts:
            with self.subTest(conflict=conflict), self.assertRaises(RoleConfigError):
                runner._configured_command(
                    ["codex", "exec", *conflict, "--json", "-"], policy, "max"
                )

        allowed = runner._configured_command(
            ["codex", "exec", "--enable", "other_feature", "--", "--model=literal"],
            policy,
            "max",
        )
        self.assertEqual(allowed[-2:], ["--", "--model=literal"])

    def test_role_config_errors_happen_before_prompt_read_or_event_creation(self) -> None:
        cases = (
            (
                "effort without config",
                False,
                ("--role", "implementation", "--reasoning-effort", "max"),
                [sys.executable, "-c", "pass"],
                "requires an active",
            ),
            (
                "missing role",
                True,
                ("--reasoning-effort", "max"),
                ["codex", "exec", "-"],
                "--role is required",
            ),
            (
                "missing effort",
                True,
                ("--role", "implementation"),
                ["codex", "exec", "-"],
                "--reasoning-effort is required",
            ),
            (
                "non codex child",
                True,
                ("--role", "implementation", "--reasoning-effort", "max"),
                [sys.executable, "-c", "pass"],
                "codex exec",
            ),
            (
                "child conflict",
                True,
                ("--role", "implementation", "--reasoning-effort", "max"),
                ["codex", "exec", "--model", "other", "-"],
                "conflicting",
            ),
        )
        for name, active, options, child, expected_error in cases:
            with self.subTest(name=name), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                subprocess.run(["git", "init", "-q", str(root)], check=True)
                if active:
                    config = root / ".codex-orchestrator" / "config.ini"
                    config.parent.mkdir()
                    config.write_text(VALID_ROLE_CONFIG, encoding="utf-8")
                prompt = root / "missing-prompt.md"
                events = root / "events.jsonl"

                result = subprocess.run(
                    [
                        sys.executable,
                        str(SCRIPT),
                        "run",
                        "--repo",
                        str(root),
                        "--events",
                        str(events),
                        "--prompt",
                        str(prompt),
                        *options,
                        "--",
                        *child,
                    ],
                    check=False,
                    text=True,
                    capture_output=True,
                    cwd=ROOT,
                )

                self.assertEqual(result.returncode, 2, result.stderr)
                self.assertIn(expected_error, result.stderr)
                self.assertNotIn("could not read prompt", result.stderr)
                self.assertFalse(events.exists())

    def test_invalid_existing_role_config_fails_before_prompt_and_events(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            subprocess.run(["git", "init", "-q", str(root)], check=True)
            config = root / ".codex-orchestrator" / "config.ini"
            config.parent.mkdir()
            config.write_text(
                VALID_ROLE_CONFIG.replace("version=1", "version=2"), encoding="utf-8"
            )
            events = root / "events.jsonl"

            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "run",
                    "--repo",
                    str(root),
                    "--role",
                    "implementation",
                    "--reasoning-effort",
                    "max",
                    "--events",
                    str(events),
                    "--prompt",
                    str(root / "missing.md"),
                    "--",
                    "codex",
                    "exec",
                    "-",
                ],
                check=False,
                text=True,
                capture_output=True,
                cwd=ROOT,
            )

        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn("version must be 1", result.stderr)
        self.assertNotIn("could not read prompt", result.stderr)
        self.assertFalse(events.exists())

    def test_configured_model_with_nul_fails_before_prompt_and_events(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            subprocess.run(["git", "init", "-q", str(root)], check=True)
            config = root / ".codex-orchestrator" / "config.ini"
            config.parent.mkdir()
            config.write_text(
                VALID_ROLE_CONFIG.replace("gpt-5.6-sol", "gpt-5.6-sol\x00invalid"),
                encoding="utf-8",
            )
            events = root / "events.jsonl"

            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "run",
                    "--repo",
                    str(root),
                    "--role",
                    "implementation",
                    "--reasoning-effort",
                    "max",
                    "--events",
                    str(events),
                    "--prompt",
                    str(root / "missing.md"),
                    "--",
                    "codex",
                    "exec",
                    "-",
                ],
                check=False,
                text=True,
                capture_output=True,
                cwd=ROOT,
            )

            self.assertEqual(result.returncode, 2, result.stderr)
            self.assertIn("must not contain NUL bytes", result.stderr)
            self.assertNotIn("Traceback", result.stderr)
            self.assertFalse(events.exists())

    def test_child_exit_codes_are_propagated(self) -> None:
        for exit_code in (0, 7):
            with self.subTest(exit_code=exit_code), tempfile.TemporaryDirectory() as tmp:
                result, _ = run_child(Path(tmp), f"raise SystemExit({exit_code})")

            self.assertEqual(result.returncode, exit_code, result.stderr)
            self.assertIn(f"exited code={exit_code}", result.stdout)

    @unittest.skipUnless(os.name == "posix", "signal return codes require POSIX")
    def test_signal_killed_child_exit_code_is_normalized(self) -> None:
        code = "import os,signal; os.kill(os.getpid(), signal.SIGTERM)"
        with tempfile.TemporaryDirectory() as tmp:
            result, _ = run_child(Path(tmp), code, prompt=b"", timeout=5)

        self.assertEqual(result.returncode, 128 + signal.SIGTERM, result.stderr)
        self.assertIn("exited code=143", result.stdout)

    def test_child_stderr_passes_through_runner_stderr(self) -> None:
        code = (
            "import sys; sys.stdin.buffer.read(); "
            "sys.stderr.write('native diagnostic\\n'); sys.stderr.flush()"
        )
        with tempfile.TemporaryDirectory() as tmp:
            result, _ = run_child(Path(tmp), code, timeout=5)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, "native diagnostic\n")

    def test_events_file_is_flushed_after_each_line(self) -> None:
        first = b'{"type":"turn.started"}\n'
        second = b'{"type":"turn.completed"}\n'
        code = textwrap.dedent(
            """\
            import pathlib
            import sys
            import time

            events = pathlib.Path(sys.argv[1])
            first = b'{"type":"turn.started"}\\n'
            sys.stdout.buffer.write(first)
            sys.stdout.buffer.flush()
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                if events.read_bytes() == first:
                    break
                time.sleep(0.01)
            else:
                raise SystemExit(9)
            sys.stdout.buffer.write(b'{"type":"turn.completed"}\\n')
            sys.stdout.buffer.flush()
            """
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            events = root / "events.jsonl"
            result, _ = run_child(
                root, code, child_args=(str(events),), events=events, timeout=7
            )
            captured = events.read_bytes()

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(captured, first + second)

    def test_capture_write_failure_stops_child(self) -> None:
        class FailingEvents(io.BytesIO):
            def write(self, data: bytes) -> int:
                raise OSError("simulated capture failure")

        code = textwrap.dedent(
            """\
            import os
            import pathlib
            import sys
            import time

            pathlib.Path(sys.argv[1]).write_text(str(os.getpid()))
            while True:
                sys.stdout.write('{"type":"turn.started"}\\n')
                sys.stdout.flush()
                time.sleep(0.01)
            """
        )
        with tempfile.TemporaryDirectory() as tmp:
            pid_path = Path(tmp) / "child.pid"
            stdout = io.StringIO()
            stderr = io.StringIO()
            with (
                contextlib.redirect_stdout(stdout),
                contextlib.redirect_stderr(stderr),
            ):
                result = runner._run_child(
                    [sys.executable, "-c", code, str(pid_path)],
                    b"",
                    FailingEvents(),
                    "test-agent",
                    time.monotonic(),
                )
            child_pid = int(pid_path.read_text(encoding="utf-8"))

        self.assertNotEqual(result, 0)
        self.assertFalse(self._process_is_running(child_pid))
        self.assertIn("could not write events file", stderr.getvalue())

    def test_existing_events_file_is_untouched_and_child_is_not_launched(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            events = root / "events.jsonl"
            marker = root / "launched"
            original = b"existing events\n"
            events.write_bytes(original)
            code = f"import pathlib; pathlib.Path({str(marker)!r}).write_text('launched')"
            result, _ = run_child(root, code, events=events)

            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(events.read_bytes(), original)
            self.assertFalse(marker.exists())
            self.assertIn("could not create events file", result.stderr)

    def test_missing_prompt_does_not_create_events_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            prompt = root / "missing.md"
            events = root / "events.jsonl"
            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "run",
                    "--events",
                    str(events),
                    "--prompt",
                    str(prompt),
                    "--",
                    sys.executable,
                    "-c",
                    "raise SystemExit(0)",
                ],
                check=False,
                text=True,
                capture_output=True,
                cwd=ROOT,
            )

            self.assertNotEqual(result.returncode, 0)
            self.assertFalse(events.exists())
            self.assertIn("could not read prompt", result.stderr)

    def test_missing_child_command_is_a_usage_error(self) -> None:
        for extra in ((), ("--",)):
            with self.subTest(extra=extra), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                prompt = root / "prompt.md"
                events = root / "events.jsonl"
                prompt.write_bytes(b"")
                result = subprocess.run(
                    [
                        sys.executable,
                        str(SCRIPT),
                        "run",
                        "--events",
                        str(events),
                        "--prompt",
                        str(prompt),
                        *extra,
                    ],
                    check=False,
                    text=True,
                    capture_output=True,
                    cwd=ROOT,
                )

                self.assertNotEqual(result.returncode, 0)
                self.assertIn("a child command is required after --", result.stderr)
                self.assertFalse(events.exists())

    def test_broken_display_pipe_does_not_stop_event_capture(self) -> None:
        raw = b'{"type":"turn.started"}\n{"type":"turn.completed"}\n'
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            prompt = root / "prompt.md"
            events = root / "events.jsonl"
            prompt.write_bytes(b"")
            code = (
                f"import sys,time; sys.stdout.buffer.write({raw!r}); "
                "sys.stdout.buffer.flush(); time.sleep(0.2)"
            )
            process = subprocess.Popen(
                [
                    sys.executable,
                    str(SCRIPT),
                    "run",
                    "--events",
                    str(events),
                    "--prompt",
                    str(prompt),
                    "--",
                    sys.executable,
                    "-c",
                    code,
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=ROOT,
            )
            assert process.stdout is not None
            process.stdout.close()
            process.stdout = None
            _, stderr = process.communicate(timeout=5)

            self.assertEqual(process.returncode, 0, stderr.decode(errors="replace"))
            self.assertEqual(events.read_bytes(), raw)

    def test_unread_display_pipe_does_not_stall_event_capture(self) -> None:
        line = b'{"type":"turn.started"}\n'
        line_count = 60_000
        raw = line * line_count
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            prompt = root / "prompt.md"
            events = root / "events.jsonl"
            prompt.write_bytes(b"")
            code = (
                "import sys; "
                f"sys.stdout.buffer.write({line!r} * {line_count}); "
                "sys.stdout.buffer.flush()"
            )
            process = subprocess.Popen(
                [
                    sys.executable,
                    str(SCRIPT),
                    "run",
                    "--events",
                    str(events),
                    "--prompt",
                    str(prompt),
                    "--",
                    sys.executable,
                    "-c",
                    code,
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=ROOT,
            )
            started = time.monotonic()
            try:
                returncode = process.wait(timeout=5)
                elapsed = time.monotonic() - started
                assert process.stderr is not None
                stderr = process.stderr.read()
            finally:
                if process.poll() is None:
                    process.kill()
                    process.wait()
                if process.stdout is not None:
                    process.stdout.close()
                if process.stderr is not None:
                    process.stderr.close()

            self.assertEqual(returncode, 0, stderr.decode(errors="replace"))
            self.assertLess(elapsed, 3)
            self.assertEqual(events.read_bytes(), raw)

    @unittest.skipUnless(os.name == "posix", "process-group escalation requires POSIX")
    def test_stop_child_escalates_when_sigterm_is_ignored(self) -> None:
        code = (
            "import signal,time; signal.signal(signal.SIGTERM, signal.SIG_IGN); "
            "print('ready', flush=True); time.sleep(60)"
        )
        process = subprocess.Popen(
            [sys.executable, "-c", code],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=True,
        )
        assert process.stdout is not None
        self.assertEqual(process.stdout.readline(), b"ready\n")
        try:
            started = time.monotonic()
            with mock.patch.object(runner, "_TERMINATE_TIMEOUT", 0.2):
                runner._stop_child(process)
            elapsed = time.monotonic() - started
        finally:
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait()
            process.stdout.close()
            assert process.stderr is not None
            process.stderr.close()

        self.assertIsNotNone(process.returncode)
        self.assertLess(elapsed, 2)

    @unittest.skipUnless(os.name == "posix", "process-group cancellation requires POSIX")
    def test_sigterm_stops_child_and_grandchild(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            prompt = root / "prompt.md"
            events = root / "events.jsonl"
            grandchild_pid_path = root / "grandchild.pid"
            prompt.write_bytes(b"")
            grandchild_code = "import time; time.sleep(60)"
            child_code = (
                "import pathlib,subprocess,sys,time; "
                f"child=subprocess.Popen([sys.executable,'-c',{grandchild_code!r}]); "
                "pathlib.Path(sys.argv[1]).write_text(str(child.pid)); "
                "sys.stdout.write('{\"type\":\"turn.started\"}\\n'); sys.stdout.flush(); "
                "time.sleep(60)"
            )
            process = subprocess.Popen(
                [
                    sys.executable,
                    str(SCRIPT),
                    "run",
                    "--events",
                    str(events),
                    "--prompt",
                    str(prompt),
                    "--",
                    sys.executable,
                    "-c",
                    child_code,
                    str(grandchild_pid_path),
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=ROOT,
            )
            deadline = time.monotonic() + 5
            while not grandchild_pid_path.exists() and time.monotonic() < deadline:
                time.sleep(0.05)
            self.assertTrue(grandchild_pid_path.exists(), "child did not launch in time")
            grandchild_pid = int(grandchild_pid_path.read_text(encoding="utf-8"))

            process.send_signal(signal.SIGTERM)
            stdout, stderr = process.communicate(timeout=10)

            self.assertNotEqual(process.returncode, 0, stderr.decode(errors="replace"))
            self.assertIn(b"exited code=", stdout)
            deadline = time.monotonic() + 2
            while self._process_is_running(grandchild_pid) and time.monotonic() < deadline:
                time.sleep(0.05)
            self.assertFalse(self._process_is_running(grandchild_pid))

    @unittest.skipUnless(os.name == "posix", "signal output draining requires POSIX")
    def test_sigterm_keeps_draining_child_shutdown_output(self) -> None:
        payload = b"x" * (1024 * 1024)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            prompt = root / "prompt.md"
            events = root / "events.jsonl"
            child_pid_path = root / "child.pid"
            prompt.write_bytes(b"")
            child_code = textwrap.dedent(
                """\
                import os
                import pathlib
                import signal
                import sys

                payload = b"x" * (1024 * 1024)

                def handle_signal(_signum, _frame):
                    sys.stdout.buffer.write(payload)
                    sys.stdout.buffer.flush()
                    raise SystemExit(0)

                signal.signal(signal.SIGTERM, handle_signal)
                pathlib.Path(sys.argv[1]).write_text(str(os.getpid()))
                print("ready", flush=True)
                signal.pause()
                """
            )
            process = subprocess.Popen(
                [
                    sys.executable,
                    str(SCRIPT),
                    "run",
                    "--events",
                    str(events),
                    "--prompt",
                    str(prompt),
                    "--",
                    sys.executable,
                    "-c",
                    child_code,
                    str(child_pid_path),
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=ROOT,
            )
            deadline = time.monotonic() + 3
            while time.monotonic() < deadline:
                try:
                    if events.read_bytes() == b"ready\n" and child_pid_path.exists():
                        break
                except FileNotFoundError:
                    pass
                time.sleep(0.01)
            self.assertTrue(child_pid_path.exists(), "child did not launch in time")
            child_pid = int(child_pid_path.read_text(encoding="utf-8"))

            started = time.monotonic()
            process.send_signal(signal.SIGTERM)
            try:
                stdout, stderr = process.communicate(timeout=4)
            finally:
                if process.poll() is None:
                    process.kill()
                    process.wait()
                if self._process_is_running(child_pid):
                    os.killpg(child_pid, signal.SIGKILL)
            elapsed = time.monotonic() - started

            self.assertEqual(process.returncode, 128 + signal.SIGTERM, stderr.decode())
            self.assertLess(elapsed, 3)
            self.assertEqual(events.read_bytes(), b"ready\n" + payload)
            self.assertIn(b"exited code=0", stdout)

    def test_top_level_help_lists_run_subcommand(self) -> None:
        result = subprocess.run(
            [sys.executable, str(SCRIPT), "--help"],
            check=False,
            text=True,
            capture_output=True,
            cwd=ROOT,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("run", result.stdout)
        self.assertIn("run --help", result.stdout)

    @staticmethod
    def _process_is_running(pid: int) -> bool:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        stat_path = Path(f"/proc/{pid}/stat")
        try:
            fields = stat_path.read_text(encoding="utf-8").split()
        except OSError:
            return True
        return len(fields) < 3 or fields[2] != "Z"


if __name__ == "__main__":
    unittest.main()
