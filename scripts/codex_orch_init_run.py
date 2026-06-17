#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path


DEFAULT_VERIFICATION_POLICY = {
    "required": [
        "git diff review",
        "pytest",
        "artifact manifest check",
    ],
    "forbidden": [
        "delete tests to pass",
        "shrink validation ranges without justification",
        "accept training/RL changes on a single stochastic pass",
    ],
    "nondeterministic_rollouts": [
        "seeded determinism where supported",
        "metric-threshold checks on eval rollouts",
        "regression bands on reward/return instead of equality assertions",
    ],
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def atomic_write_text(path: Path, text: str) -> None:
    tmp_path = path.with_name(f".{path.name}.tmp")
    tmp_path.write_text(text, encoding="utf-8")
    os.replace(tmp_path, path)


def write_text(path: Path, text: str, *, force: bool) -> None:
    if path.exists() and not force:
        return
    atomic_write_text(path, text)


def write_json(path: Path, payload: object, *, force: bool) -> None:
    text = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    write_text(path, text, force=force)


def validate_run_id(parser: argparse.ArgumentParser, run_id: str) -> None:
    if not run_id or run_id in {".", ".."} or "/" in run_id or "\\" in run_id:
        parser.error("--run-id must be a single path segment")


def build_state(repo: Path, run_id: str) -> dict[str, object]:
    return {
        "run_id": run_id,
        "repo": str(repo),
        "created_at": utc_now(),
        "status": "active",
        "sessions": [],
        "verification_policy": DEFAULT_VERIFICATION_POLICY,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Create a codex-orchestrator run ledger."
    )
    parser.add_argument("--repo", required=True, help="Repository root for the run.")
    parser.add_argument("--run-id", required=True, help="Run id / directory name.")
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite existing scaffold files for this run.",
    )
    args = parser.parse_args()
    validate_run_id(parser, args.run_id)
    return args


def main() -> int:
    args = parse_args()
    repo = Path(args.repo).expanduser().resolve()
    if not repo.exists() or not repo.is_dir():
        raise SystemExit(f"ERROR: repo does not exist or is not a directory: {repo}")

    run_dir = repo / ".codex-orchestrator" / "runs" / args.run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    write_json(run_dir / "state.json", build_state(repo, args.run_id), force=args.force)
    write_text(run_dir / "events.jsonl", "", force=args.force)
    write_json(run_dir / "tasks.json", {"tasks": []}, force=args.force)
    write_text(run_dir / "verification.jsonl", "", force=args.force)
    write_text(run_dir / "review.md", "# Review\n\n", force=args.force)
    write_text(run_dir / "consensus.md", "# Consensus\n\n", force=args.force)
    write_text(run_dir / "final-report.md", "# Final Report\n\n", force=args.force)

    print(run_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
