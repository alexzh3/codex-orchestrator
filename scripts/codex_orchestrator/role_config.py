"""Opt-in, repository-local role policy for managed Codex executions."""

from __future__ import annotations

import configparser
import stat
import subprocess
from dataclasses import dataclass
from pathlib import Path

CONFIG_RELATIVE_PATH = Path(".codex-orchestrator/config.ini")
ROLES = ("implementation", "review", "planning", "planning_review")
REASONING_EFFORTS = ("low", "medium", "high", "xhigh", "max", "ultra")
_ROOT_SECTIONS = ("meta", "defaults")
_ROLE_PREFIX = "role."
_EXCLUDE_PATTERN = "/.codex-orchestrator/"
_GENERATED_CONFIG = """\
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


class RoleConfigError(ValueError):
    """Raised when a role configuration cannot be loaded or applied."""


@dataclass(frozen=True)
class RolePolicy:
    """Resolved settings for one orchestration role."""

    model: str | None
    speed: str | None
    reasoning_efforts: tuple[str, ...]


@dataclass(frozen=True)
class RoleConfiguration:
    """A validated role configuration."""

    path: Path
    roles: dict[str, RolePolicy]

    def policy_for(self, role: str) -> RolePolicy:
        try:
            return self.roles[role]
        except KeyError as exc:
            raise RoleConfigError(f"unknown role {role!r}") from exc


def role_config_path(repo: Path) -> Path:
    """Return the absolute opt-in configuration path for ``repo``."""

    return repository_root(repo) / CONFIG_RELATIVE_PATH


def repository_root(repo: Path) -> Path:
    """Resolve an existing path to its containing Git worktree root."""

    try:
        candidate = repo.expanduser().resolve()
        candidate_metadata = candidate.stat()
    except FileNotFoundError as exc:
        raise RoleConfigError(f"repository is not a directory: {repo}") from exc
    except (OSError, RuntimeError) as exc:
        raise RoleConfigError(f"could not inspect repository path {repo}: {exc}") from exc
    if not stat.S_ISDIR(candidate_metadata.st_mode):
        raise RoleConfigError(f"repository is not a directory: {candidate}")
    try:
        result = subprocess.run(
            ["git", "-C", str(candidate), "rev-parse", "--show-toplevel"],
            check=False,
            text=True,
            capture_output=True,
        )
    except OSError as exc:
        raise RoleConfigError(f"could not resolve Git worktree: {exc}") from exc
    if result.returncode != 0:
        detail = result.stderr.strip() or "not a Git worktree"
        raise RoleConfigError(f"could not resolve Git worktree for {candidate}: {detail}")
    root_text = result.stdout.strip()
    if not root_text:
        raise RoleConfigError(f"could not resolve Git worktree for {candidate}: empty result")
    try:
        return Path(root_text).resolve()
    except (OSError, RuntimeError) as exc:
        raise RoleConfigError(f"could not inspect Git worktree root {root_text}: {exc}") from exc


def load_role_config(repo: Path) -> RoleConfiguration | None:
    """Load the repository policy, returning ``None`` when it is not enabled."""

    repo = repository_root(repo)

    path = repo / CONFIG_RELATIVE_PATH
    try:
        metadata = path.stat()
    except FileNotFoundError as exc:
        try:
            path.lstat()
        except FileNotFoundError:
            return None
        except OSError as inspect_exc:
            raise RoleConfigError(
                f"could not inspect configuration {path}: {inspect_exc}"
            ) from inspect_exc
        raise RoleConfigError(f"configuration target does not exist: {path}") from exc
    except OSError as exc:
        raise RoleConfigError(f"could not inspect configuration {path}: {exc}") from exc
    if not stat.S_ISREG(metadata.st_mode):
        raise RoleConfigError(f"configuration is not a file: {path}")

    parser = configparser.ConfigParser(interpolation=None, strict=True)
    try:
        with path.open(encoding="utf-8") as handle:
            parser.read_file(handle)
    except (configparser.Error, OSError, UnicodeError) as exc:
        raise RoleConfigError(f"could not read {path}: {exc}") from exc

    _validate_sections(parser)
    _validate_keys(parser, "meta", {"version"}, {"version"})
    if parser.get("meta", "version").strip() != "1":
        raise RoleConfigError("[meta] version must be 1")

    _validate_keys(parser, "defaults", {"model", "speed"}, set())
    default_model = _optional_value(parser, "defaults", "model")
    default_speed = _optional_value(parser, "defaults", "speed")
    _validate_speed(default_speed, "[defaults]")

    policies: dict[str, RolePolicy] = {}
    for role in ROLES:
        section = f"{_ROLE_PREFIX}{role}"
        _validate_keys(
            parser,
            section,
            {"model", "speed", "reasoning_efforts"},
            {"reasoning_efforts"},
        )
        role_model = _optional_value(parser, section, "model")
        role_speed = _optional_value(parser, section, "speed")
        _validate_speed(role_speed, f"[{section}]")
        policies[role] = RolePolicy(
            model=default_model if role_model is None else role_model,
            speed=default_speed if role_speed is None else role_speed,
            reasoning_efforts=_parse_efforts(parser.get(section, "reasoning_efforts"), section),
        )

    return RoleConfiguration(path=path, roles=policies)


def initialize_role_config(repo: Path) -> Path:
    """Create the default role policy without overwriting an existing file."""

    repo = repository_root(repo)

    path = repo / CONFIG_RELATIVE_PATH
    try:
        path.lstat()
    except FileNotFoundError:
        pass
    except OSError as exc:
        raise RoleConfigError(f"could not inspect configuration {path}: {exc}") from exc
    else:
        raise RoleConfigError(f"configuration already exists: {path}")

    _ensure_local_exclusion(repo)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("x", encoding="utf-8") as handle:
            handle.write(_GENERATED_CONFIG)
    except FileExistsError as exc:
        raise RoleConfigError(f"configuration already exists: {path}") from exc
    except OSError as exc:
        raise RoleConfigError(f"could not create {path}: {exc}") from exc
    return path


def _validate_sections(parser: configparser.ConfigParser) -> None:
    if parser.defaults():
        raise RoleConfigError("[DEFAULT] is not supported")
    expected = {*_ROOT_SECTIONS, *(f"{_ROLE_PREFIX}{role}" for role in ROLES)}
    actual = set(parser.sections())
    missing = sorted(expected - actual)
    unknown = sorted(actual - expected)
    if missing:
        raise RoleConfigError(f"missing section(s): {', '.join(missing)}")
    if unknown:
        raise RoleConfigError(f"unknown section(s): {', '.join(unknown)}")


def _validate_keys(
    parser: configparser.ConfigParser,
    section: str,
    allowed: set[str],
    required: set[str],
) -> None:
    actual = set(parser[section])
    unknown = sorted(actual - allowed)
    missing = sorted(required - actual)
    if unknown:
        raise RoleConfigError(f"unknown key(s) in [{section}]: {', '.join(unknown)}")
    if missing:
        raise RoleConfigError(f"missing key(s) in [{section}]: {', '.join(missing)}")


def _optional_value(
    parser: configparser.ConfigParser, section: str, option: str
) -> str | None:
    if option not in parser[section]:
        return None
    value = parser.get(section, option).strip()
    if not value:
        raise RoleConfigError(f"[{section}] {option} must not be empty")
    if "\x00" in value:
        raise RoleConfigError(f"[{section}] {option} must not contain NUL bytes")
    return value


def _validate_speed(speed: str | None, location: str) -> None:
    if speed is not None and speed != "fast":
        raise RoleConfigError(f"{location} speed must be 'fast' when set")


def _parse_efforts(value: str, section: str) -> tuple[str, ...]:
    efforts = tuple(part.strip() for part in value.split(","))
    if not efforts or any(not effort for effort in efforts):
        raise RoleConfigError(f"[{section}] reasoning_efforts must not be empty")
    if len(set(efforts)) != len(efforts):
        raise RoleConfigError(f"[{section}] reasoning_efforts must be unique")
    invalid = [effort for effort in efforts if effort not in REASONING_EFFORTS]
    if invalid:
        raise RoleConfigError(
            f"[{section}] unsupported reasoning effort(s): {', '.join(invalid)}"
        )
    indexes = [REASONING_EFFORTS.index(effort) for effort in efforts]
    if indexes != sorted(indexes):
        raise RoleConfigError(
            f"[{section}] reasoning_efforts must follow this order: "
            f"{', '.join(REASONING_EFFORTS)}"
        )
    return efforts


def _ensure_local_exclusion(repo: Path) -> None:
    try:
        result = subprocess.run(
            ["git", "-C", str(repo), "rev-parse", "--git-path", "info/exclude"],
            check=False,
            text=True,
            capture_output=True,
        )
    except OSError as exc:
        raise RoleConfigError(f"could not locate Git exclude file: {exc}") from exc
    if result.returncode != 0:
        detail = result.stderr.strip() or "not a Git repository"
        raise RoleConfigError(f"could not locate Git exclude file: {detail}")

    exclude_path = Path(result.stdout.strip())
    if not exclude_path.is_absolute():
        exclude_path = repo / exclude_path
    try:
        existing = exclude_path.read_text(encoding="utf-8") if exclude_path.exists() else ""
        if _EXCLUDE_PATTERN not in existing.splitlines():
            with exclude_path.open("a", encoding="utf-8") as handle:
                if existing and not existing.endswith("\n"):
                    handle.write("\n")
                handle.write(f"{_EXCLUDE_PATTERN}\n")
    except OSError as exc:
        raise RoleConfigError(f"could not update {exclude_path}: {exc}") from exc

    try:
        verification = subprocess.run(
            [
                "git",
                "-C",
                str(repo),
                "check-ignore",
                "-q",
                ".codex-orchestrator/.ignore-check",
            ],
            check=False,
            text=True,
            capture_output=True,
        )
    except OSError as exc:
        raise RoleConfigError(f"could not verify local Git exclusion: {exc}") from exc
    if verification.returncode != 0:
        detail = verification.stderr.strip() or "ignore rule did not match"
        raise RoleConfigError(f"could not verify local Git exclusion: {detail}")
