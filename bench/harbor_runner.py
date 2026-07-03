from __future__ import annotations

import json
import os
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
AGENT_IMPORT_PATH = "bench.harbor_agent:CodexOrchestratorAgent"
CODEX_EXEC_RE = re.compile(r"\bcodex(?:-cli)?\s+exec\b")
GPT_TOKEN_FIELDS = ("input_tokens", "output_tokens", "total_tokens")


def run_tblite_task_via_harbor(
    task_id: str,
    plugin_dir: Path,
    *,
    dataset: str,
    model: str,
    effort: str,
    jobs_dir: Path,
    oauth_token_env: str,
    timeout: int | float | None,
) -> dict[str, object]:
    """Run one OpenThoughts-TBLite task with Harbor and normalize its result."""

    import importlib.util
    import shutil
    import subprocess
    import tempfile

    harbor_exe = shutil.which("harbor")
    if harbor_exe is None and importlib.util.find_spec("harbor") is None:
        raise RuntimeError(
            "Harbor is not installed or not on PATH; install Harbor and run "
            "`harbor download openthoughts-tblite` before real TBLite runs."
        )
    if harbor_exe is None:
        harbor_exe = "harbor"

    plugin_dir = Path(plugin_dir).expanduser().resolve()
    if not plugin_dir.is_dir():
        raise RuntimeError(f"CODEX_ORCH_PLUGIN_DIR must be a directory: {plugin_dir}")

    jobs_dir = Path(jobs_dir)
    jobs_dir.mkdir(parents=True, exist_ok=True)
    # Isolate each invocation in its own fresh output dir so a task that crashes
    # before writing a result can never inherit another task's older result.json
    # from a shared jobs tree (which would report the wrong pass/fail + tokens).
    run_output_dir = Path(
        tempfile.mkdtemp(prefix=f"{_safe_slug(task_id)}-", dir=jobs_dir)
    )
    env_values = _resolve_harbor_env(plugin_dir, oauth_token_env)
    env_file_path = _write_env_file(env_values, tempfile_module=tempfile)

    command = [
        harbor_exe,
        "run",
        "-d",
        dataset,
        "-i",
        task_id,
        "--agent-import-path",
        AGENT_IMPORT_PATH,
        "-m",
        model,
        "--agent-kwarg",
        f"reasoning_effort={effort}",
        "-n",
        "1",
        "-o",
        str(run_output_dir),
        "--env-file",
        str(env_file_path),
    ]

    # Pass the agent-facing variables through to the Harbor subprocess env (not
    # just the container --env-file) so the host-side agent that materializes the
    # plugin dir and provisions credentials can read them via os.environ.
    run_env = {**os.environ, **env_values}
    # Ensure Harbor can import `bench.harbor_agent` via --agent-import-path even
    # when invoked as an installed entrypoint (repo root is not on sys.path by
    # default in the subprocess).
    run_env["PYTHONPATH"] = os.pathsep.join(
        part
        for part in (str(ROOT), str(ROOT / "scripts"), run_env.get("PYTHONPATH", ""))
        if part
    )
    start = time.monotonic()
    try:
        completed = subprocess.run(
            command,
            check=False,
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=run_env,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(
            f"Harbor TBLite task {task_id!r} timed out after {timeout} seconds"
        ) from exc
    finally:
        try:
            env_file_path.unlink()
        except OSError:
            pass

    measured_wall_seconds = time.monotonic() - start
    try:
        result_path, result_payload = _find_trial_result(run_output_dir)
    except RuntimeError:
        if completed.returncode != 0:
            raise RuntimeError(
                f"Harbor TBLite task {task_id!r} exited with {completed.returncode} "
                f"before writing a verifier result. stdout: "
                f"{_truncate(completed.stdout)} stderr: {_truncate(completed.stderr)}"
            )
        raise

    _verify_result_identity(result_payload, task_id, result_path)
    normalized = _normalize_trial_result(
        result_payload,
        result_path=result_path,
        measured_wall_seconds=measured_wall_seconds,
    )
    if completed.returncode != 0 and normalized.get("resolved") is None:
        raise RuntimeError(
            f"Harbor TBLite task {task_id!r} exited with {completed.returncode} "
            "and did not include a verifier result."
        )
    return normalized


def _resolve_harbor_env(plugin_dir: Path, oauth_token_env: str) -> dict[str, str]:
    """Build the environment shared with the Harbor run (env file + subprocess).

    Two Claude auth modes:
    - ``credentials`` (default): reuse the operator's ``claude login`` — the agent
      uploads ``~/.claude/.credentials.json`` into the container, so no OAuth token
      is required here. ANTHROPIC_API_KEY is blanked so the CLI prefers that
      subscription credentials file over any stray API key.
    - ``token``: require ``CLAUDE_CODE_OAUTH_TOKEN`` and force Harbor's OAuth path.
    """

    auth_mode = (
        os.environ.get("CODEX_ORCH_CLAUDE_AUTH_MODE") or "credentials"
    ).strip().lower()
    if auth_mode not in ("credentials", "token"):
        raise RuntimeError(
            "CODEX_ORCH_CLAUDE_AUTH_MODE must be 'credentials' or 'token'; "
            f"got {auth_mode!r}"
        )

    env_values: dict[str, str] = {
        "CODEX_ORCH_PLUGIN_DIR": str(plugin_dir),
        "CODEX_FORCE_AUTH_JSON": "1",
        "CODEX_ORCH_CLAUDE_AUTH_MODE": auth_mode,
    }
    if auth_mode == "token":
        oauth_token = os.environ.get(oauth_token_env, "")
        if not oauth_token:
            raise RuntimeError(
                f"{oauth_token_env} is required when CODEX_ORCH_CLAUDE_AUTH_MODE=token; "
                "run `claude setup-token` and export the token, or use credentials mode."
            )
        env_values["CLAUDE_FORCE_OAUTH"] = "1"
        env_values["CLAUDE_CODE_OAUTH_TOKEN"] = oauth_token
    else:
        # Reuse the operator's uploaded credentials file. Blank any stray API key
        # and clear an inherited OAuth token so a stale host token cannot silently
        # reach Claude in credentials mode. CLAUDE_FORCE_OAUTH must be "0" (a value
        # Harbor can parse as a bool), not "" — an empty string raises a parse error.
        env_values["ANTHROPIC_API_KEY"] = ""
        env_values["CLAUDE_CODE_OAUTH_TOKEN"] = ""
        env_values["CLAUDE_FORCE_OAUTH"] = "0"
    return env_values


def _write_env_file(
    values: dict[str, str],
    *,
    tempfile_module: Any,
) -> Path:
    handle = tempfile_module.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        prefix="codex-orch-harbor-",
        suffix=".env",
        delete=False,
    )
    path = Path(handle.name)
    with handle:
        for key, value in values.items():
            handle.write(f"{key}={_dotenv_quote(value)}\n")
    return path


def _dotenv_quote(value: str) -> str:
    escaped = (
        value.replace("\\", "\\\\")
        .replace("\n", "\\n")
        .replace("\r", "\\r")
        .replace('"', '\\"')
    )
    return f'"{escaped}"'


def _safe_slug(value: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip("-")
    return slug or "task"


def _verify_result_identity(
    payload: dict[str, object], task_id: str, result_path: Path
) -> None:
    """Guard against reporting another task's result under this task_id."""
    task_name = payload.get("task_name")
    if isinstance(task_name, str) and task_name:
        if task_id != task_name and task_id not in task_name and task_name not in task_id:
            raise RuntimeError(
                f"Harbor result at {result_path} is for task {task_name!r}, not the "
                f"requested {task_id!r}; refusing to report a mismatched result."
            )


def _find_trial_result(jobs_dir: Path) -> tuple[Path, dict[str, object]]:
    candidates = sorted(
        jobs_dir.rglob("result.json"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    for path in candidates:
        payload = _load_json_object(path)
        if _looks_like_trial_result(payload):
            return path, payload
        for nested in _trial_results_from_job(payload):
            return path, nested
    raise RuntimeError(f"Harbor result file is missing under {jobs_dir}")


def _load_json_object(path: Path) -> dict[str, object]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Could not read Harbor result file {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise RuntimeError(f"Harbor result file {path} must contain a JSON object")
    return payload


def _looks_like_trial_result(payload: dict[str, object]) -> bool:
    return (
        isinstance(payload.get("trial_name"), str)
        and isinstance(payload.get("task_name"), str)
    )


def _trial_results_from_job(payload: dict[str, object]) -> list[dict[str, object]]:
    trial_results = payload.get("trial_results")
    if not isinstance(trial_results, list):
        return []
    return [item for item in trial_results if isinstance(item, dict)]


def _normalize_trial_result(
    payload: dict[str, object],
    *,
    result_path: Path,
    measured_wall_seconds: float,
) -> dict[str, object]:
    rewards = _verifier_rewards(payload)
    resolved = _resolved_from_rewards(rewards)
    score = _score_from_rewards(rewards)
    tokens = _token_usage_from_result(payload)
    gpt_tokens = _gpt_token_usage_from_trial_dir(result_path)
    combined_tokens = _combined_token_usage(tokens, gpt_tokens)
    codex_sessions_spawned, real_orchestration, orchestration_note = (
        _real_orchestration_from_trial_dir(result_path)
    )
    result = {
        "resolved": resolved,
        "verifier_exit": _verifier_exit(payload),
        "score": score,
        "wall_seconds": _wall_seconds(payload, measured_wall_seconds),
        "tokens": tokens,
        "claude_tokens": tokens,
        "gpt_tokens": gpt_tokens,
        "combined_tokens": combined_tokens,
        "raw_result_path": str(result_path),
        "verifier_rewards": rewards,
        "exception": payload.get("exception_info"),
        "codex_sessions_spawned": codex_sessions_spawned,
        "real_orchestration": real_orchestration,
        "orchestration_note": orchestration_note,
    }
    if gpt_tokens is None:
        result["token_note"] = "GPT/Codex token usage unavailable: no collected Codex session JSONL logs found"
    elif not any(_non_negative_int(gpt_tokens.get(field)) is not None for field in GPT_TOKEN_FIELDS):
        result["token_note"] = "GPT/Codex token usage unavailable: collected Codex logs had no token usage events"
    return result


def _verifier_rewards(payload: dict[str, object]) -> dict[str, object]:
    verifier_result = payload.get("verifier_result")
    if not isinstance(verifier_result, dict):
        raise RuntimeError("Harbor result does not include verifier_result")
    rewards = verifier_result.get("rewards")
    if isinstance(rewards, dict) and rewards:
        return dict(rewards)
    # Grading must come only from Harbor's verifier rewards; do not fall back to
    # any other field, so a score is never inferred from a weaker signal.
    raise RuntimeError(
        "Harbor verifier_result does not include a non-empty 'rewards' object"
    )


def _resolved_from_rewards(rewards: dict[str, object]) -> bool:
    for key in ("resolved", "passed", "success"):
        if key in rewards:
            return _reward_to_bool(rewards[key], key)
    if "reward" in rewards:
        return _reward_to_bool(rewards["reward"], "reward")
    if len(rewards) == 1:
        key, value = next(iter(rewards.items()))
        return _reward_to_bool(value, key)
    raise RuntimeError(
        "Harbor verifier rewards must include resolved/passed/success/reward "
        "or a single numeric reward"
    )


def _reward_to_bool(value: object, key: str) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        if value in (0, 1):
            return bool(value)
        return float(value) > 0.0
    raise RuntimeError(f"Harbor verifier reward {key!r} must be numeric or boolean")


def _score_from_rewards(rewards: dict[str, object]) -> int | float | None:
    for key in ("score", "reward", "resolved", "passed", "success"):
        value = rewards.get(key)
        if isinstance(value, bool):
            return int(value)
        if isinstance(value, (int, float)):
            return value
    if len(rewards) == 1:
        value = next(iter(rewards.values()))
        if isinstance(value, bool):
            return int(value)
        if isinstance(value, (int, float)):
            return value
    return None


def _verifier_exit(payload: dict[str, object]) -> int | None:
    verifier_result = payload.get("verifier_result")
    if isinstance(verifier_result, dict):
        for key in ("exit_code", "return_code", "verifier_exit"):
            value = verifier_result.get(key)
            if type(value) is int and value >= 0:
                return value
    return None


def _wall_seconds(
    payload: dict[str, object],
    measured_wall_seconds: float,
) -> float:
    started = _parse_datetime(payload.get("started_at"))
    finished = _parse_datetime(payload.get("finished_at"))
    if started is not None and finished is not None:
        return max(0.0, (finished - started).total_seconds())
    return round(max(0.0, measured_wall_seconds), 6)


def _parse_datetime(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    normalized = value.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(normalized)
    except ValueError:
        return None


def _token_usage_from_result(payload: dict[str, object]) -> dict[str, object] | None:
    agent_result = payload.get("agent_result")
    if isinstance(agent_result, dict):
        usage = _token_usage_from_context(agent_result)
        if usage is not None:
            return usage
    stats = payload.get("stats")
    if isinstance(stats, dict):
        return _token_usage_from_context(stats)
    return None


def _token_usage_from_context(context: dict[str, object]) -> dict[str, object] | None:
    input_tokens = _non_negative_int(context.get("n_input_tokens"))
    output_tokens = _non_negative_int(context.get("n_output_tokens"))
    cache_tokens = _non_negative_int(context.get("n_cache_tokens"))
    cost_usd = _non_negative_number(context.get("cost_usd"))
    if (
        input_tokens is None
        and output_tokens is None
        and cache_tokens is None
        and cost_usd is None
    ):
        return None
    total_tokens = (
        input_tokens + output_tokens
        if input_tokens is not None and output_tokens is not None
        else None
    )
    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cache_read_input_tokens": cache_tokens,
        "cache_creation_input_tokens": None,
        "total_tokens": total_tokens,
        "cost_usd": cost_usd,
        "num_turns_reported": None,
    }


def _gpt_token_usage_from_trial_dir(result_path: Path) -> dict[str, object] | None:
    trial_dir = result_path.parent
    paths = sorted(trial_dir.rglob("codex-sessions/**/*.jsonl"))
    if not paths:
        return None

    sessions: dict[str, dict[str, object]] = {}
    for path in paths:
        session_key, usage = _gpt_token_usage_from_jsonl(path)
        key = session_key or str(path)
        if usage is None:
            sessions.setdefault(key, _empty_gpt_token_usage())
            continue
        # Codex usage snapshots are cumulative within a session, and copied
        # exec logs may duplicate a rollout. Keep the largest complete snapshot
        # per session key, then sum across sessions.
        current = sessions.get(key)
        if current is None or _usage_score(usage) >= _usage_score(current):
            sessions[key] = usage

    totals = _empty_gpt_token_usage()
    for usage in sessions.values():
        for field in GPT_TOKEN_FIELDS:
            totals[field] = _sum_optional_ints(totals[field], usage.get(field))
    totals["num_sessions"] = len(sessions)
    totals["cost_usd"] = None
    return totals


def _gpt_token_usage_from_jsonl(path: Path) -> tuple[str | None, dict[str, object] | None]:
    session_key: str | None = None
    last_turn_usage: dict[str, object] | None = None
    last_token_count_total: dict[str, object] | None = None
    accumulated_token_count: dict[str, object] = _empty_gpt_token_usage()
    saw_accumulated_token_count = False
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return str(path), None

    for line in lines:
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(event, dict):
            continue
        session_key = session_key or _event_thread_id(event)
        event_type = _codex_event_type(event)
        if event_type == "turn.completed":
            usage = event.get("usage")
            if isinstance(usage, dict):
                last_turn_usage = _gpt_token_usage_from_mapping(usage)
        elif event_type == "token_count":
            total_usage, last_usage = _token_count_usages(event)
            if total_usage is not None:
                last_token_count_total = total_usage
            elif last_usage is not None:
                saw_accumulated_token_count = True
                for field in GPT_TOKEN_FIELDS:
                    accumulated_token_count[field] = _sum_optional_ints(
                        accumulated_token_count.get(field),
                        last_usage.get(field),
                    )

    if last_turn_usage is not None:
        return session_key or str(path), last_turn_usage
    if last_token_count_total is not None:
        return session_key or str(path), last_token_count_total
    if saw_accumulated_token_count:
        return session_key or str(path), accumulated_token_count
    return session_key or str(path), None


def _codex_event_type(event: dict[str, object]) -> str | None:
    payload = event.get("payload")
    if isinstance(payload, dict) and isinstance(payload.get("type"), str):
        return payload["type"]
    if isinstance(event.get("type"), str):
        return event["type"]
    return None


def _event_thread_id(event: dict[str, object]) -> str | None:
    value = event.get("thread_id")
    if isinstance(value, str) and value:
        return value
    payload = event.get("payload")
    if isinstance(payload, dict):
        value = payload.get("thread_id")
        if isinstance(value, str) and value:
            return value
    return None


def _token_count_usages(
    event: dict[str, object],
) -> tuple[dict[str, object] | None, dict[str, object] | None]:
    payload = event.get("payload")
    source = payload if isinstance(payload, dict) else event
    info = source.get("info")
    if not isinstance(info, dict):
        return None, None
    total = info.get("total_token_usage")
    last = info.get("last_token_usage")
    return (
        _gpt_token_usage_from_mapping(total) if isinstance(total, dict) else None,
        _gpt_token_usage_from_mapping(last) if isinstance(last, dict) else None,
    )


def _gpt_token_usage_from_mapping(mapping: dict[str, object]) -> dict[str, object]:
    input_tokens = _non_negative_int(mapping.get("input_tokens"))
    output_tokens = _non_negative_int(mapping.get("output_tokens"))
    total_tokens = _non_negative_int(mapping.get("total_tokens"))
    if total_tokens is None and input_tokens is not None and output_tokens is not None:
        total_tokens = input_tokens + output_tokens
    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": total_tokens,
    }


def _empty_gpt_token_usage() -> dict[str, object]:
    return {field: None for field in GPT_TOKEN_FIELDS}


def _usage_score(usage: dict[str, object]) -> tuple[int, int]:
    known = 0
    total = 0
    for field in GPT_TOKEN_FIELDS:
        value = _non_negative_int(usage.get(field))
        if value is not None:
            known += 1
            total += value
    return known, total


def _combined_token_usage(
    claude_tokens: dict[str, object] | None,
    gpt_tokens: dict[str, object] | None,
) -> dict[str, object]:
    combined: dict[str, object] = {}
    for field in GPT_TOKEN_FIELDS:
        claude_value = (
            _non_negative_int(claude_tokens.get(field))
            if isinstance(claude_tokens, dict)
            else None
        )
        gpt_value = (
            _non_negative_int(gpt_tokens.get(field))
            if isinstance(gpt_tokens, dict)
            else None
        )
        combined[field] = _sum_optional_ints(claude_value, gpt_value)
    return combined


def _sum_optional_ints(left: object, right: object) -> int | None:
    left_int = _non_negative_int(left)
    right_int = _non_negative_int(right)
    if left_int is None:
        return right_int
    if right_int is None:
        return left_int
    return left_int + right_int


def _non_negative_int(value: object) -> int | None:
    if type(value) is int and value >= 0:
        return value
    return None


def _non_negative_number(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)) and value >= 0:
        return float(value)
    return None


def _real_orchestration_from_trial_dir(
    result_path: Path,
) -> tuple[int | None, bool | None, str | None]:
    trajectory_path = _claude_trajectory_path(result_path)
    if trajectory_path is None:
        return None, None, "claude-code.txt not found for Harbor trial"
    count = _count_codex_exec_dispatches(trajectory_path)
    return count, count > 0, None


def _claude_trajectory_path(result_path: Path) -> Path | None:
    trial_dir = result_path.parent
    direct = trial_dir / "agent" / "claude-code.txt"
    if direct.is_file():
        return direct
    candidates = sorted(trial_dir.rglob("claude-code.txt"))
    return candidates[0] if candidates else None


def _count_codex_exec_dispatches(trajectory_path: Path) -> int:
    count = 0
    try:
        lines = trajectory_path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return 0
    for line in lines:
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        count += _count_codex_exec_bash_tools(event)
    return count


def _count_codex_exec_bash_tools(value: object) -> int:
    if isinstance(value, list):
        return sum(_count_codex_exec_bash_tools(item) for item in value)
    if not isinstance(value, dict):
        return 0

    tool_name = value.get("name") or value.get("tool_name")
    if isinstance(tool_name, str) and tool_name.lower() == "bash":
        return 1 if _contains_codex_exec_command(value) else 0

    return sum(_count_codex_exec_bash_tools(item) for item in value.values())


def _contains_codex_exec_command(value: object) -> bool:
    if isinstance(value, str):
        return CODEX_EXEC_RE.search(value) is not None
    if isinstance(value, list):
        return any(_contains_codex_exec_command(item) for item in value)
    if isinstance(value, dict):
        return any(_contains_codex_exec_command(item) for item in value.values())
    return False


def _truncate(value: str | None, limit: int = 1200) -> str:
    if not value:
        return ""
    if len(value) <= limit:
        return value
    return value[:limit] + "...[truncated]"
