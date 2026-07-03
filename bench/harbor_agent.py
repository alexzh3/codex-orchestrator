from __future__ import annotations

import logging
import os
import shlex
from pathlib import Path, PurePosixPath
from typing import Any


try:  # Harbor is an optional external tool; keep this module importable without it.
    from harbor.agents.installed.claude_code import ClaudeCode
except Exception:  # pragma: no cover - exercised on hosts without Harbor.
    ClaudeCode = None  # type: ignore[assignment]


class _FallbackClaudeCode:
    """Small test fallback used when Harbor is not importable in this Python.

    Real Harbor runs import the actual ``ClaudeCode`` class. The repository test
    environment may only have the ``harbor`` executable installed under another
    Python version, so this fallback lets mocked unit tests cover our glue code.
    """

    def __init__(
        self,
        logs_dir: Path,
        *args: object,
        model_name: str | None = None,
        reasoning_effort: str | None = None,
        extra_env: dict[str, str] | None = None,
        **kwargs: object,
    ) -> None:
        del args, kwargs
        self.logs_dir = Path(logs_dir)
        self.model_name = model_name
        self._extra_env = dict(extra_env or {})
        self._resolved_flags: dict[str, object] = {}
        if reasoning_effort:
            self._resolved_flags["reasoning_effort"] = reasoning_effort
        self._resolved_flags.setdefault("permission_mode", "bypassPermissions")
        self._resolved_env_vars: dict[str, str] = {}
        self._version: str | None = None
        self.logger = logging.getLogger(__name__)

    @staticmethod
    def name() -> str:
        return "claude-code"

    def _init_model_info(self) -> None:
        return None

    def _get_env(self, key: str) -> str | None:
        return self._extra_env.get(key) or os.environ.get(key)

    async def install(self, environment: Any) -> None:
        del environment

    async def exec_as_root(
        self,
        environment: Any,
        command: str,
        env: dict[str, str] | None = None,
        cwd: str | None = None,
        timeout_sec: int | None = None,
    ) -> Any:
        return await environment.exec(
            command=command,
            user="root",
            env=env,
            cwd=cwd,
            timeout_sec=timeout_sec,
        )

    async def exec_as_agent(
        self,
        environment: Any,
        command: str,
        env: dict[str, str] | None = None,
        cwd: str | None = None,
        timeout_sec: int | None = None,
    ) -> Any:
        return await environment.exec(
            command=command,
            env=env,
            cwd=cwd,
            timeout_sec=timeout_sec,
        )

    def build_cli_flags(self) -> str:
        parts: list[str] = []
        effort = self._resolved_flags.get("reasoning_effort")
        if effort:
            parts.extend(["--effort", str(effort)])
        permission_mode = self._resolved_flags.get("permission_mode")
        if permission_mode:
            parts.append(f"--permission-mode={permission_mode}")
        return " ".join(parts)

    async def run(self, instruction: str, environment: Any, context: Any) -> None:
        del context
        env = dict(self._resolved_env_vars)
        if self.model_name:
            env["ANTHROPIC_MODEL"] = self.model_name
        token = self._get_env("CLAUDE_CODE_OAUTH_TOKEN")
        if token:
            env["CLAUDE_CODE_OAUTH_TOKEN"] = token
        flags = self.build_cli_flags()
        flags_arg = f"{flags} " if flags else ""
        await self.exec_as_agent(
            environment,
            command=(
                'export PATH="$HOME/.local/bin:$PATH"; '
                "claude --verbose --output-format=stream-json "
                f"{flags_arg}"
                f"--print -- {shlex.quote(instruction)} 2>&1 </dev/null | tee "
                "/logs/agent/claude-code.txt"
            ),
            env=env,
        )


if ClaudeCode is None:  # pragma: no cover - branch depends on host Harbor install.
    ClaudeCode = _FallbackClaudeCode  # type: ignore[misc,assignment]


def _truthy_env(value: str | None) -> bool:
    if value is None:
        return False
    return value.strip().lower() in {"1", "true", "yes", "on"}


class CodexOrchestratorAgent(ClaudeCode):  # type: ignore[misc,valid-type]
    """Harbor agent that runs the codex-orchestrator Claude workflow."""

    FORCED_MODEL = "claude-opus-4-8"
    FORCED_EFFORT = "max"
    FORCED_CODEX_MODEL = "gpt-5.5"
    FORCED_CODEX_REASONING_EFFORT = "xhigh"
    FORCED_CODEX_SERVICE_TIER = "default"
    NAME = "codex-orchestrator"
    REMOTE_PLUGIN_DIR = PurePosixPath("/tmp/codex-orch-plugin")
    REMOTE_CODEX_HOME = PurePosixPath("/tmp/codex-home")
    REMOTE_CODEX_SECRETS_DIR = PurePosixPath("/tmp/codex-secrets")
    REMOTE_CLAUDE_SECRETS_DIR = PurePosixPath("/tmp/claude-secrets")
    REMOTE_LOGS_DIR = PurePosixPath("/logs/agent")
    CODEX_SESSIONS_SUBDIR = "codex-sessions"
    ORCHESTRATE_PREFIX = "/codex-orchestrator:orchestrate "
    # "credentials": reuse the operator's local `claude login` by uploading
    # ~/.claude/.credentials.json into the container (mirrors codex auth.json).
    # "token": rely on Harbor's CLAUDE_FORCE_OAUTH + CLAUDE_CODE_OAUTH_TOKEN path.
    DEFAULT_CLAUDE_AUTH_MODE = "credentials"

    def __init__(self, logs_dir: Path, *args: object, **kwargs: object) -> None:
        # Harbor's ClaudeCode uses ``model_name`` to set ANTHROPIC_MODEL and
        # ``reasoning_effort`` to emit ``--effort``. Force both here so CLI
        # ``-m`` or agent kwargs cannot weaken the TBLite benchmark contract.
        kwargs["model_name"] = self.FORCED_MODEL
        kwargs["reasoning_effort"] = self.FORCED_EFFORT
        super().__init__(logs_dir, *args, **kwargs)
        self.model_name = self.FORCED_MODEL
        if hasattr(self, "_init_model_info"):
            self._init_model_info()
        self._resolved_flags["reasoning_effort"] = self.FORCED_EFFORT
        self._resolved_env_vars["CODEX_HOME"] = self.REMOTE_CODEX_HOME.as_posix()
        self._extra_env["CODEX_HOME"] = self.REMOTE_CODEX_HOME.as_posix()
        # The plugin's monitoring helpers reference ${CLAUDE_PLUGIN_ROOT}; it is
        # unset for ad-hoc Bash tool calls in headless mode, so pin it to the
        # uploaded plugin dir the orchestrate skill actually runs from.
        self._resolved_env_vars["CLAUDE_PLUGIN_ROOT"] = self.REMOTE_PLUGIN_DIR.as_posix()
        self._extra_env["CLAUDE_PLUGIN_ROOT"] = self.REMOTE_PLUGIN_DIR.as_posix()

    @staticmethod
    def name() -> str:
        return CodexOrchestratorAgent.NAME

    def build_cli_flags(self) -> str:
        base_flags = super().build_cli_flags()
        plugin_flag = (
            "--plugin-dir "
            f"{shlex.quote(self.REMOTE_PLUGIN_DIR.as_posix())}"
        )
        return " ".join(part for part in (base_flags, plugin_flag) if part)

    def _get_required_env(self, name: str) -> str:
        value = self._get_env(name)
        if not value:
            raise RuntimeError(f"{name} is required for the TBLite Harbor agent")
        return value

    def _plugin_dir(self) -> Path:
        raw = self._get_required_env("CODEX_ORCH_PLUGIN_DIR")
        plugin_dir = Path(raw).expanduser()
        if not plugin_dir.is_dir():
            raise RuntimeError(
                "CODEX_ORCH_PLUGIN_DIR must point to an existing plugin directory; "
                f"got {plugin_dir}"
            )
        return plugin_dir

    def _codex_auth_json_path(self) -> Path:
        explicit = self._get_env("CODEX_AUTH_JSON_PATH")
        if explicit:
            path = Path(explicit).expanduser()
            if not path.is_file():
                raise RuntimeError(
                    f"CODEX_AUTH_JSON_PATH points to a missing auth file: {path}"
                )
            return path

        if not _truthy_env(self._get_env("CODEX_FORCE_AUTH_JSON")):
            raise RuntimeError(
                "CODEX_FORCE_AUTH_JSON=1 is required so Codex auth.json can be "
                "provisioned inside the Harbor container"
            )

        path = Path.home() / ".codex" / "auth.json"
        if not path.is_file():
            raise RuntimeError(
                f"CODEX_FORCE_AUTH_JSON is set but {path} does not exist"
            )
        return path

    def _claude_auth_mode(self) -> str:
        mode = (
            self._get_env("CODEX_ORCH_CLAUDE_AUTH_MODE")
            or self.DEFAULT_CLAUDE_AUTH_MODE
        ).strip().lower()
        if mode not in ("credentials", "token"):
            raise RuntimeError(
                "CODEX_ORCH_CLAUDE_AUTH_MODE must be 'credentials' or 'token'; "
                f"got {mode!r}"
            )
        return mode

    def _claude_credentials_path(self) -> Path:
        explicit = self._get_env("CODEX_ORCH_CLAUDE_CREDENTIALS_FILE")
        if explicit:
            path = Path(explicit).expanduser()
            if not path.is_file():
                raise RuntimeError(
                    "CODEX_ORCH_CLAUDE_CREDENTIALS_FILE points to a missing "
                    f"credentials file: {path}"
                )
            return path
        path = Path.home() / ".claude" / ".credentials.json"
        if not path.is_file():
            raise RuntimeError(
                f"Claude credentials auth mode requires {path} (run `claude login`, "
                "or set CODEX_ORCH_CLAUDE_AUTH_MODE=token with CLAUDE_CODE_OAUTH_TOKEN)"
            )
        return path

    async def _provision_claude_credentials(self, environment: Any) -> None:
        """Reuse the operator's local Claude subscription login.

        Uploads ``~/.claude/.credentials.json`` verbatim into the container the
        same way Codex ``auth.json`` is provisioned. The file is never parsed or
        logged here. ANTHROPIC_API_KEY is blanked (via the env file) so the CLI
        prefers this credentials file over any stray API key.
        """
        credentials_path = self._claude_credentials_path()
        remote_secrets_dir = self.REMOTE_CLAUDE_SECRETS_DIR.as_posix()
        remote_credentials_path = (
            self.REMOTE_CLAUDE_SECRETS_DIR / ".credentials.json"
        ).as_posix()
        await self.exec_as_agent(
            environment,
            command=(
                f"mkdir -p ~/.claude {shlex.quote(remote_secrets_dir)} && "
                f"chmod 700 ~/.claude {shlex.quote(remote_secrets_dir)}"
            ),
        )
        await environment.upload_file(credentials_path, remote_credentials_path)
        if getattr(environment, "default_user", None) is not None:
            await self.exec_as_root(
                environment,
                command=(
                    f"chown {environment.default_user} "
                    f"{shlex.quote(remote_credentials_path)}"
                ),
            )
        # Copy into place with tight perms, then remove the staging copy so the
        # secret only ever lives at the intended 0600 credential path.
        await self.exec_as_agent(
            environment,
            command=(
                f"chmod 600 {shlex.quote(remote_credentials_path)} && "
                f"cp {shlex.quote(remote_credentials_path)} ~/.claude/.credentials.json && "
                "chmod 600 ~/.claude/.credentials.json && "
                f"rm -f {shlex.quote(remote_credentials_path)}"
            ),
        )

    async def _install_codex(self, environment: Any) -> None:
        check = await environment.exec(
            command=(
                "if [ -s ~/.nvm/nvm.sh ]; then . ~/.nvm/nvm.sh; fi; "
                "command -v codex >/dev/null 2>&1"
            )
        )
        if check.return_code == 0:
            self.logger.debug("Codex is already available in the Harbor container")
            return

        await self.exec_as_root(
            environment,
            command=(
                "if ldd --version 2>&1 | grep -qi musl || [ -f /etc/alpine-release ]; then"
                "  apk add --no-cache curl bash nodejs npm ripgrep;"
                " elif command -v apt-get &>/dev/null; then"
                "  apt-get update && apt-get install -y curl ripgrep;"
                " elif command -v yum &>/dev/null; then"
                "  yum install -y curl ripgrep;"
                " else"
                '  echo "Warning: No known package manager found, assuming curl is available" >&2;'
                " fi"
            ),
            env={"DEBIAN_FRONTEND": "noninteractive"},
        )
        await self.exec_as_agent(
            environment,
            command=(
                "set -euo pipefail; "
                "if ldd --version 2>&1 | grep -qi musl || [ -f /etc/alpine-release ]; then"
                "  npm install -g @openai/codex@latest;"
                " else"
                "  curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.40.2/install.sh | bash &&"
                '  export NVM_DIR="$HOME/.nvm" &&'
                '  \\. "$NVM_DIR/nvm.sh" || true &&'
                "  command -v nvm &>/dev/null || { echo 'Error: NVM failed to load' >&2; exit 1; } &&"
                "  nvm install 22 && nvm alias default 22 && npm -v &&"
                "  npm install -g @openai/codex@latest;"
                " fi && "
                "codex --version"
            ),
            env={"NVM_NODEJS_ORG_MIRROR": "https://nodejs.org/dist"},
        )
        # Put codex + its node runtime on the AGENT's runtime PATH. Harbor launches
        # `claude` with `export PATH="$HOME/.local/bin:$PATH"`, but nvm's versioned
        # bin dir is not on that PATH — so without this the orchestrate skill's
        # `codex exec` dispatch finds no codex (`which codex` -> nothing) and Claude
        # silently solves tasks itself (degenerate, non-representative run). Resolve
        # both with nvm loaded, as the agent, and symlink into ~/.local/bin.
        await self.exec_as_agent(
            environment,
            command=(
                "set -u; if [ -s ~/.nvm/nvm.sh ]; then . ~/.nvm/nvm.sh; fi; "
                "mkdir -p ~/.local/bin; "
                "for bin in node codex; do "
                '  p="$(command -v "$bin" 2>/dev/null || true)"; '
                '  if [ -n "$p" ] && [ "$p" != "$HOME/.local/bin/$bin" ]; then '
                '    ln -sf "$p" ~/.local/bin/"$bin"; '
                "  fi; "
                "done; "
                'echo "codex-on-path: $(command -v codex 2>/dev/null || echo MISSING)"'
            ),
        )
        # Best-effort: also expose on /usr/local/bin for globally-installed codex
        # (e.g. the musl/alpine `npm install -g` path where codex is on root's PATH).
        await self.exec_as_root(
            environment,
            command=(
                "for bin in node codex; do"
                '  BIN_PATH="$(which "$bin" 2>/dev/null || true)";'
                '  if [ -n "$BIN_PATH" ] && [ "$BIN_PATH" != "/usr/local/bin/$bin" ]; then'
                '    ln -sf "$BIN_PATH" "/usr/local/bin/$bin";'
                "  fi;"
                " done"
            ),
        )

    async def _provision_codex_auth(self, environment: Any) -> None:
        auth_json_path = self._codex_auth_json_path()
        remote_codex_home = self.REMOTE_CODEX_HOME.as_posix()
        remote_secrets_dir = self.REMOTE_CODEX_SECRETS_DIR.as_posix()
        remote_auth_path = (self.REMOTE_CODEX_SECRETS_DIR / "auth.json").as_posix()
        await self.exec_as_agent(
            environment,
            command=(
                f'mkdir -p "$CODEX_HOME" ~/.codex '
                f"{shlex.quote(remote_secrets_dir)} && "
                f'chmod 700 "$CODEX_HOME" ~/.codex {shlex.quote(remote_secrets_dir)}'
            ),
            env={"CODEX_HOME": remote_codex_home},
        )
        await environment.upload_file(auth_json_path, remote_auth_path)
        if getattr(environment, "default_user", None) is not None:
            await self.exec_as_root(
                environment,
                command=f"chown {environment.default_user} {shlex.quote(remote_auth_path)}",
            )
        # auth.json stays in the secrets dir (the symlinks below point at it), so
        # lock it to 0600 rather than removing it.
        await self.exec_as_agent(
            environment,
            command=(
                f"chmod 600 {shlex.quote(remote_auth_path)}\n"
                f'ln -sf {shlex.quote(remote_auth_path)} "$CODEX_HOME/auth.json"\n'
                f"ln -sf {shlex.quote(remote_auth_path)} ~/.codex/auth.json"
            ),
            env={"CODEX_HOME": remote_codex_home},
        )

    def _codex_config_values(self) -> dict[str, str]:
        return {
            "model": (
                self._get_env("CODEX_ORCH_CODEX_MODEL")
                or self.FORCED_CODEX_MODEL
            ),
            "model_reasoning_effort": (
                self._get_env("CODEX_ORCH_CODEX_REASONING_EFFORT")
                or self.FORCED_CODEX_REASONING_EFFORT
            ),
            "service_tier": (
                self._get_env("CODEX_ORCH_CODEX_SERVICE_TIER")
                or self.FORCED_CODEX_SERVICE_TIER
            ),
        }

    async def _provision_codex_config(self, environment: Any) -> None:
        config_lines = "\n".join(
            f"{key} = {_toml_string(value)}"
            for key, value in self._codex_config_values().items()
        )
        remote_codex_home = self.REMOTE_CODEX_HOME.as_posix()
        await self.exec_as_agent(
            environment,
            command=(
                'mkdir -p "$CODEX_HOME" ~/.codex\n'
                'cat >"$CODEX_HOME/config.toml" <<\'TOML\'\n'
                f"{config_lines}\n"
                "TOML\n"
                'ln -sf "$CODEX_HOME/config.toml" ~/.codex/config.toml'
            ),
            env={"CODEX_HOME": remote_codex_home},
        )

    async def _upload_plugin_dir(self, environment: Any) -> None:
        plugin_dir = self._plugin_dir()
        remote_plugin_dir = self.REMOTE_PLUGIN_DIR.as_posix()
        await self.exec_as_root(
            environment,
            command=f"rm -rf {shlex.quote(remote_plugin_dir)} && mkdir -p {shlex.quote(remote_plugin_dir)}",
        )
        # Harbor's BaseEnvironment.upload_dir(source, target) documents target as
        # the destination directory. This path needs one real Harbor run to verify
        # the task image preserves directory contents exactly as the docs imply.
        await environment.upload_dir(plugin_dir, remote_plugin_dir)
        if getattr(environment, "default_user", None) is not None:
            await self.exec_as_root(
                environment,
                command=f"chown -R {environment.default_user} {shlex.quote(remote_plugin_dir)}",
            )

    async def install(self, environment: Any) -> None:
        await super().install(environment)
        await self._install_codex(environment)
        await self._provision_codex_auth(environment)
        await self._provision_codex_config(environment)
        if self._claude_auth_mode() == "credentials":
            await self._provision_claude_credentials(environment)
        await self._upload_plugin_dir(environment)

    def _orchestrate_instruction(self, instruction: str) -> str:
        if instruction.startswith(self.ORCHESTRATE_PREFIX):
            return instruction
        return f"{self.ORCHESTRATE_PREFIX}{instruction}"

    async def run(self, instruction: str, environment: Any, context: Any) -> None:
        # Collect Codex logs even if the Claude run exits nonzero, otherwise GPT
        # token usage and real-orchestration evidence would be lost on failures.
        try:
            await super().run(
                self._orchestrate_instruction(instruction), environment, context
            )
        finally:
            await self._collect_codex_logs(environment)

    async def _collect_codex_logs(self, environment: Any) -> None:
        remote_logs_dir = self.REMOTE_LOGS_DIR.as_posix()
        sessions_dir = (
            self.REMOTE_LOGS_DIR / self.CODEX_SESSIONS_SUBDIR
        ).as_posix()
        exec_logs_dir = (
            self.REMOTE_LOGS_DIR / self.CODEX_SESSIONS_SUBDIR / "exec-logs"
        ).as_posix()
        try:
            await environment.exec(
                command=(
                    f"mkdir -p {shlex.quote(sessions_dir)} {shlex.quote(exec_logs_dir)}\n"
                    'if [ -d "$CODEX_HOME/sessions" ]; then\n'
                    f'  cp -a "$CODEX_HOME/sessions/." {shlex.quote(sessions_dir)}/ '
                    "2>/dev/null || true\n"
                    "fi\n"
                    'if [ -d "$CODEX_HOME" ]; then\n'
                    '  find "$CODEX_HOME" -type f -name "*.jsonl" '
                    '    ! -path "$CODEX_HOME/sessions/*" '
                    f"    -exec cp -a {{}} {shlex.quote(exec_logs_dir)}/ \\; "
                    "2>/dev/null || true\n"
                    "fi\n"
                ),
                env={"CODEX_HOME": self.REMOTE_CODEX_HOME.as_posix()},
            )
            self.logger.debug(
                "Collected Codex logs from %s into %s",
                self.REMOTE_CODEX_HOME,
                remote_logs_dir,
            )
        except Exception as exc:  # pragma: no cover - exact Harbor errors vary.
            self.logger.debug("Could not collect Codex logs from Harbor container: %s", exc)


def _toml_string(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'
