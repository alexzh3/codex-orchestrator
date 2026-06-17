#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def run_git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True)


def validate_name(parser: argparse.ArgumentParser, name: str) -> None:
    if not name or "/" in name or "\\" in name or name in {".", ".."}:
        parser.error("--name must be a single path segment")


def default_branch(name: str) -> str:
    if name.startswith("codex-") and len(name) > len("codex-"):
        return f"codex/{name[len('codex-'):]}"
    return f"codex/{name}"


def find_active_state(repo: Path) -> Path:
    runs_dir = repo / ".codex-orchestrator" / "runs"
    candidates: list[Path] = []
    if runs_dir.exists():
        for path in runs_dir.glob("*/state.json"):
            try:
                state = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if state.get("status") == "active":
                candidates.append(path)
    if not candidates:
        raise SystemExit("ERROR: no active run state found under .codex-orchestrator/runs")
    return max(candidates, key=lambda path: path.stat().st_mtime)


def atomic_write_json(path: Path, payload: object) -> None:
    tmp_path = path.with_name(f".{path.name}.tmp")
    tmp_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(tmp_path, path)


def upsert_session(
    state_path: Path,
    *,
    name: str,
    thread_id: str,
    mode: str,
    branch: str,
    worktree: Path,
) -> None:
    state = json.loads(state_path.read_text(encoding="utf-8"))
    sessions = state.setdefault("sessions", [])
    session = {
        "name": name,
        "thread_id": thread_id,
        "mode": mode,
        "rollout_path": None,
        "branch": branch,
        "worktree": str(worktree),
        "status": "idle",
        "last_seen_at": utc_now(),
    }
    for index, existing in enumerate(sessions):
        if isinstance(existing, dict) and existing.get("name") == name:
            sessions[index] = {**existing, **session}
            break
    else:
        sessions.append(session)
    atomic_write_json(state_path, state)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Create a Codex git worktree and register it in the active run ledger."
    )
    parser.add_argument("--name", required=True, help="Session name, for example codex-a.")
    parser.add_argument("--repo", default=".", help="Repository root.")
    parser.add_argument("--base", default="main", help="Base ref for the new branch.")
    parser.add_argument("--branch", help="Branch name. Defaults to codex/<name suffix>.")
    parser.add_argument("--worktree", help="Worktree path. Defaults to ../repo-<name>.")
    parser.add_argument("--thread-id", help="Thread id if already known.")
    parser.add_argument("--mode", choices=("ide", "exec"), default="exec")
    args = parser.parse_args()
    validate_name(parser, args.name)
    return args


def main() -> int:
    args = parse_args()
    repo = Path(args.repo).expanduser().resolve()
    if not repo.exists() or not repo.is_dir():
        raise SystemExit(f"ERROR: repo does not exist or is not a directory: {repo}")

    branch = args.branch or default_branch(args.name)
    worktree = (
        Path(args.worktree).expanduser()
        if args.worktree
        else repo.parent / f"repo-{args.name}"
    ).resolve()
    state_path = find_active_state(repo)

    run_git(repo, "worktree", "add", str(worktree), "-b", branch, args.base)
    upsert_session(
        state_path,
        name=args.name,
        thread_id=args.thread_id or f"pending:{args.name}",
        mode=args.mode,
        branch=branch,
        worktree=worktree,
    )
    print(json.dumps({"branch": branch, "worktree": str(worktree), "state": str(state_path)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
