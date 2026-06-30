from __future__ import annotations

import hashlib
import fnmatch
import json
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_DIR = ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from codex_orch import validate_benchmark_result  # noqa: E402


BENCHMARK_SCHEMA = ROOT / "schemas" / "benchmark-result.schema.json"
LOCAL_MINI_SUITE = "local-mini"


def load_case(path: Path) -> dict[str, object]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return payload


def _case_dict(case: dict[str, object] | Path) -> dict[str, object]:
    return load_case(case) if isinstance(case, Path) else case


def _schema_fields() -> set[str]:
    schema = json.loads(BENCHMARK_SCHEMA.read_text(encoding="utf-8"))
    properties = schema.get("properties")
    if not isinstance(properties, dict):
        raise ValueError(f"{BENCHMARK_SCHEMA} is missing object properties")
    return set(properties)


def _validate_payload(payload: dict[str, object]) -> None:
    extra = sorted(set(payload) - _schema_fields())
    if extra:
        raise ValueError(f"benchmark result has schema-extra field(s): {', '.join(extra)}")
    validate_benchmark_result(payload)


def _string_field(case: dict[str, object], field: str) -> str:
    value = case.get(field)
    if not isinstance(value, str) or not value:
        raise ValueError(f"case is missing non-empty string field {field}")
    return value


def _int_field(case: dict[str, object], field: str) -> int:
    value = case.get(field)
    if type(value) is not int or value < 0:
        raise ValueError(f"case field {field} must be a non-negative integer")
    return value


def _number_field(case: dict[str, object], field: str) -> int | float:
    value = case.get(field)
    if not isinstance(value, (int, float)) or value < 0:
        raise ValueError(f"case field {field} must be a non-negative number")
    return value


def _acceptance_command(case: dict[str, object]) -> str:
    acceptance = case.get("acceptance")
    if not isinstance(acceptance, dict):
        raise ValueError("case acceptance must be an object")
    command = acceptance.get("command")
    if not isinstance(command, str) or not command:
        raise ValueError("case acceptance.command must be a non-empty string")
    return command


def _case_fingerprint(case_id: str) -> int:
    return sum((index + 1) * ord(char) for index, char in enumerate(case_id))


def _safe_name(value: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9_.-]+", "-", value).strip("-") or "ref"
    digest = hashlib.sha1(value.encode("utf-8")).hexdigest()[:8]
    return f"{slug[:60]}-{digest}"


def plugin_ref_dir(plugin_ref: str, work_dir: Path) -> Path:
    candidate = Path(plugin_ref).expanduser()
    if candidate.is_absolute() or candidate.exists():
        return candidate.resolve()
    return work_dir / "plugin-refs" / _safe_name(plugin_ref)


def build_claude_argv(case: dict[str, object], plugin_ref: str, *, work_dir: Path) -> list[str]:
    prompt = _string_field(case, "prompt")
    max_budget = _number_field(case, "max_budget_usd")
    return [
        "claude",
        "-p",
        "--plugin-dir",
        str(plugin_ref_dir(plugin_ref, work_dir)),
        "--permission-mode",
        "bypassPermissions",
        "--max-budget-usd",
        str(max_budget),
        "--output-format",
        "stream-json",
        "--verbose",
        f"/codex-orchestrator:workflow {prompt}",
    ]


def _git_output(args: list[str], *, cwd: Path) -> str | None:
    result = subprocess.run(
        ["git", *args],
        check=False,
        cwd=cwd,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


def _git_lines(args: list[str], *, cwd: Path) -> list[str]:
    output = _git_output(args, cwd=cwd)
    if output is None:
        return []
    return [line.strip() for line in output.splitlines() if line.strip()]


def _normalize_relative_path(path: str) -> str:
    normalized = path.replace("\\", "/")
    while normalized.startswith("./"):
        normalized = normalized[2:]
    return normalized


def files_within_allowlist(
    changed_paths: list[str],
    allowed_globs: list[str],
) -> tuple[bool, list[str]]:
    allowed = [_normalize_relative_path(pattern) for pattern in allowed_globs if pattern]
    offending: list[str] = []
    for raw_path in changed_paths:
        path = _normalize_relative_path(raw_path)
        if not any(path == pattern or fnmatch.fnmatchcase(path, pattern) for pattern in allowed):
            offending.append(path)
    return len(offending) == 0, offending


def changed_files(target_dir: Path) -> list[str]:
    paths: set[str] = set()
    for args in (
        ["diff", "--name-only"],
        ["diff", "--cached", "--name-only"],
        ["ls-files", "--others", "--exclude-standard"],
    ):
        paths.update(_git_lines(args, cwd=target_dir))
    return sorted(_normalize_relative_path(path) for path in paths)


def _add_worktree(repo_root: Path, ref: str, *, prefix: str, work_dir: Path) -> Path:
    work_dir.mkdir(parents=True, exist_ok=True)
    destination = Path(tempfile.mkdtemp(prefix=prefix, dir=work_dir))
    shutil.rmtree(destination)
    result = subprocess.run(
        ["git", "-C", str(repo_root), "worktree", "add", "--detach", str(destination), ref],
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if result.returncode != 0:
        raise RuntimeError(f"git worktree add failed for {ref}: {result.stderr.strip()}")
    return destination


def _remove_worktree(repo_root: Path, path: Path) -> None:
    subprocess.run(
        ["git", "-C", str(repo_root), "worktree", "remove", "--force", str(path)],
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


def _newest_run_dir(target_dir: Path) -> Path | None:
    runs_dir = target_dir / ".codex-orchestrator" / "runs"
    if not runs_dir.is_dir():
        return None
    candidates = [path for path in runs_dir.iterdir() if path.is_dir()]
    if not candidates:
        return None
    return max(candidates, key=lambda path: path.stat().st_mtime)


def _generate_benchmark_sidecar(
    *,
    target_dir: Path,
    plugin_dir: Path,
    case_id: str,
    plugin_ref: str,
    timeout_seconds: int,
) -> tuple[Path | None, str | None]:
    run_dir = _newest_run_dir(target_dir)
    if run_dir is None:
        return None, "missing .codex-orchestrator run directory"

    script = plugin_dir / "scripts" / "codex_orch.py"
    if not script.is_file():
        return None, f"missing benchmark command script: {script}"

    try:
        result = subprocess.run(
            [
                sys.executable,
                str(script),
                "benchmark",
                "--repo",
                str(target_dir),
                "--run-id",
                run_dir.name,
                "--suite",
                LOCAL_MINI_SUITE,
                "--case-id",
                case_id,
                "--plugin-ref",
                plugin_ref,
            ],
            cwd=target_dir,
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired:
        return None, "benchmark command timed out"

    sidecar_path = run_dir / "benchmark.json"
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or f"exit {result.returncode}"
        return None, f"benchmark command failed: {detail}"
    if not sidecar_path.is_file():
        return None, f"benchmark command did not write sidecar: {sidecar_path}"
    return sidecar_path, None


def _load_sidecar(path: Path | None) -> dict[str, object]:
    if path is None:
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _bool_or_none(value: object) -> bool | None:
    return value if isinstance(value, bool) else None


def _non_negative_int(value: object, default: int) -> int:
    if type(value) is int and value >= 0:
        return value
    return default


def _non_negative_number(value: object, default: float) -> float:
    if isinstance(value, (int, float)) and value >= 0:
        return float(value)
    return default


def _score(value: object, default: float = 0.0) -> float:
    number = _non_negative_number(value, default)
    return min(1.0, max(0.0, number))


def _case_allowed_globs(case: dict[str, object]) -> list[str]:
    files_allowed = case.get("files_allowed")
    if not isinstance(files_allowed, list):
        raise ValueError("case files_allowed must be a list")
    result: list[str] = []
    for value in files_allowed:
        if not isinstance(value, str) or not value:
            raise ValueError("case files_allowed entries must be non-empty strings")
        result.append(value)
    return result


def assemble_real_result(
    case: dict[str, object],
    plugin_ref: str,
    *,
    repo_commit: str | None,
    wall_seconds: float,
    sidecar: dict[str, object],
    sidecar_path: Path | None,
    sidecar_error: str | None,
    acceptance_command: str,
    acceptance_returncode: int | None,
    acceptance_timed_out: bool,
    claude_returncode: int | None,
    timed_out: bool,
    claude_argv: list[str],
    changed_paths: list[str],
    forbidden_paths: list[str],
) -> dict[str, object]:
    sidecar_validation_error: str | None = None
    if sidecar_path is not None and sidecar:
        try:
            validate_benchmark_result(sidecar)
        except SystemExit as exc:
            sidecar_validation_error = str(exc)
    sidecar_present = bool(sidecar_path is not None and sidecar and sidecar_validation_error is None)
    metric_source = sidecar if sidecar_present else {}
    tests_passed = acceptance_returncode == 0
    sidecar_failure = not sidecar_present
    forbidden_violation = bool(forbidden_paths)
    if sidecar_failure and not sidecar_error:
        sidecar_error = sidecar_validation_error or "benchmark sidecar missing or malformed"

    failure_reasons: list[str] = []
    if sidecar_failure:
        failure_reasons.append(f"missing sidecar: {sidecar_error}")
    if forbidden_violation:
        failure_reasons.append(f"forbidden-file violation: {', '.join(forbidden_paths)}")

    payload: dict[str, object] = {
        "suite": LOCAL_MINI_SUITE,
        "case_id": _string_field(case, "id"),
        "plugin_ref": plugin_ref,
        "repo_commit": repo_commit,
        "passed": tests_passed and not sidecar_failure and not forbidden_violation,
        "wall_seconds": round(wall_seconds, 6),
        "claude_turns": _non_negative_int(metric_source.get("claude_turns"), 0),
        "codex_sessions": _non_negative_int(metric_source.get("codex_sessions"), 0),
        "codex_reviews": _non_negative_int(metric_source.get("codex_reviews"), 0),
        "manual_interventions": _non_negative_int(metric_source.get("manual_interventions"), 0),
        "prompt_log_pairs_complete": bool(metric_source.get("prompt_log_pairs_complete")),
        "ledger_errors": _non_negative_int(metric_source.get("ledger_errors"), 0) + (1 if sidecar_failure else 0),
        "gate_passed": _bool_or_none(metric_source.get("gate_passed")),
        "report_score": _score(metric_source.get("report_score")),
        "external_score": {
            "tests_passed": tests_passed,
            "acceptance_command": acceptance_command,
            "acceptance_exit_code": acceptance_returncode,
            "acceptance_timed_out": acceptance_timed_out,
            "claude_exit_code": claude_returncode,
            "timed_out": timed_out,
            "sidecar_path": str(sidecar_path) if sidecar_path else None,
            "sidecar_present": sidecar_present,
            "sidecar_error": sidecar_error,
            "changed_files": changed_paths,
            "forbidden_files": forbidden_paths,
            "forbidden_file_violation": forbidden_violation,
            "failure_reason": "; ".join(failure_reasons) if failure_reasons else None,
            "claude_argv": claude_argv,
        },
    }
    _validate_payload(payload)
    return payload


def _dry_run_payload(
    case: dict[str, object],
    plugin_ref: str,
    *,
    work_dir: Path,
) -> dict[str, object]:
    case_id = _string_field(case, "id")
    fingerprint = _case_fingerprint(case_id)
    prompt_pairs_complete = fingerprint % 5 != 0
    ledger_errors = 0 if fingerprint % 7 else 1
    gate_passed = fingerprint % 4 != 0
    tests_passed = fingerprint % 6 != 0
    max_turns = _int_field(case, "max_turns")
    turns_cap = max(1, min(max_turns, 8))
    payload: dict[str, object] = {
        "suite": _string_field(case, "suite"),
        "case_id": case_id,
        "plugin_ref": plugin_ref,
        "repo_commit": f"dry-run:{_string_field(case, 'start_ref')}",
        "passed": tests_passed,
        "wall_seconds": round((fingerprint % 31) / 1000, 6),
        "claude_turns": 1 + (fingerprint % turns_cap),
        "codex_sessions": 1 + (fingerprint % 3),
        "codex_reviews": 1 if gate_passed else 0,
        "manual_interventions": fingerprint % 2,
        "prompt_log_pairs_complete": prompt_pairs_complete,
        "ledger_errors": ledger_errors,
        "gate_passed": gate_passed,
        "report_score": round(0.8 + ((fingerprint % 16) / 100), 4),
        "external_score": {
            "tests_passed": tests_passed,
            "dry_run": True,
            "acceptance_command": _acceptance_command(case),
            "claude_argv": build_claude_argv(case, plugin_ref, work_dir=work_dir),
        },
    }
    _validate_payload(payload)
    return payload


def _real_payload(
    case: dict[str, object],
    plugin_ref: str,
    *,
    repo_root: Path,
    work_dir: Path,
) -> dict[str, object]:
    case_id = _string_field(case, "id")
    timeout_seconds = _int_field(case, "timeout_seconds")
    acceptance_command = _acceptance_command(case)
    start_ref = _string_field(case, "start_ref")
    target_dir: Path | None = None
    plugin_dir: Path | None = None
    remove_plugin_worktree = False
    started = time.perf_counter()
    claude_returncode: int | None = None
    acceptance_returncode: int | None = None
    timed_out = False
    acceptance_timed_out = False

    try:
        target_dir = _add_worktree(
            repo_root,
            start_ref,
            prefix=f"target-{_safe_name(case_id)}-",
            work_dir=work_dir,
        )
        if Path(plugin_ref).expanduser().exists():
            plugin_dir = plugin_ref_dir(plugin_ref, work_dir)
        else:
            plugin_dir = _add_worktree(
                repo_root,
                plugin_ref,
                prefix=f"plugin-{_safe_name(plugin_ref)}-",
                work_dir=work_dir,
            )
            remove_plugin_worktree = True

        argv = build_claude_argv(case, plugin_ref, work_dir=plugin_dir.parent)
        argv[argv.index("--plugin-dir") + 1] = str(plugin_dir)
        try:
            claude = subprocess.run(
                argv,
                cwd=target_dir,
                check=False,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=timeout_seconds,
            )
            claude_returncode = claude.returncode
        except subprocess.TimeoutExpired:
            timed_out = True

        if not timed_out:
            try:
                acceptance = subprocess.run(
                    acceptance_command,
                    cwd=target_dir,
                    shell=True,
                    check=False,
                    text=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    timeout=timeout_seconds,
                )
                acceptance_returncode = acceptance.returncode
            except subprocess.TimeoutExpired:
                acceptance_timed_out = True

        run_changed_files = changed_files(target_dir)
        allowed_ok, forbidden_paths = files_within_allowlist(run_changed_files, _case_allowed_globs(case))
        del allowed_ok

        sidecar_path, sidecar_error = _generate_benchmark_sidecar(
            target_dir=target_dir,
            plugin_dir=plugin_dir,
            case_id=case_id,
            plugin_ref=plugin_ref,
            timeout_seconds=timeout_seconds,
        )
        sidecar = _load_sidecar(sidecar_path)
        repo_commit = _git_output(["rev-parse", "HEAD"], cwd=target_dir)
        return assemble_real_result(
            case,
            plugin_ref,
            repo_commit=repo_commit,
            wall_seconds=time.perf_counter() - started,
            sidecar=sidecar,
            sidecar_path=sidecar_path,
            sidecar_error=sidecar_error,
            acceptance_command=acceptance_command,
            acceptance_returncode=acceptance_returncode,
            acceptance_timed_out=acceptance_timed_out,
            claude_returncode=claude_returncode,
            timed_out=timed_out,
            claude_argv=argv,
            changed_paths=run_changed_files,
            forbidden_paths=forbidden_paths,
        )
    finally:
        if remove_plugin_worktree and plugin_dir is not None:
            _remove_worktree(repo_root, plugin_dir)
        if target_dir is not None:
            _remove_worktree(repo_root, target_dir)


def run_case(
    case: dict[str, object] | Path,
    plugin_ref: str,
    *,
    dry_run: bool,
    repo_root: Path,
    work_dir: Path,
) -> dict[str, object]:
    loaded_case = _case_dict(case)
    if dry_run:
        return _dry_run_payload(loaded_case, plugin_ref, work_dir=work_dir)
    return _real_payload(loaded_case, plugin_ref, repo_root=repo_root, work_dir=work_dir)
