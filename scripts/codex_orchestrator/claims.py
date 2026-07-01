from __future__ import annotations

import fnmatch


TERMINAL_TASK_STATUSES = {"complete", "blocked", "failed"}
GLOB_META_CHARS = "*?["


def normalize_glob(pattern: str) -> str:
    normalized = pattern.replace("\\", "/").strip()
    while normalized.startswith("./"):
        normalized = normalized[2:]
    return normalized


def has_glob_meta(pattern: str) -> bool:
    return any(char in pattern for char in GLOB_META_CHARS)


def glob_literal_prefix(pattern: str) -> str:
    positions = [pattern.find(char) for char in GLOB_META_CHARS if char in pattern]
    return pattern[: min(positions)] if positions else pattern


def glob_literal_dir_prefix(pattern: str) -> str:
    parts: list[str] = []
    for part in normalize_glob(pattern).split("/"):
        if has_glob_meta(part):
            break
        parts.append(part)
    return "/".join(parts)


def glob_sample(pattern: str) -> str:
    output: list[str] = []
    index = 0
    while index < len(pattern):
        char = pattern[index]
        if char == "*":
            if index + 1 < len(pattern) and pattern[index + 1] == "*":
                index += 1
            output.append("sample")
        elif char == "?":
            output.append("x")
        elif char == "[":
            close = pattern.find("]", index + 1)
            if close == -1:
                output.append(char)
            else:
                choices = pattern[index + 1 : close].lstrip("!^")
                output.append(choices[:1] or "x")
                index = close
        else:
            output.append(char)
        index += 1
    sample = "".join(output)
    return sample + "sample" if sample.endswith("/") else sample


def is_path_prefix(prefix: str, path: str) -> bool:
    prefix = prefix.rstrip("/")
    return bool(prefix) and (path == prefix or path.startswith(f"{prefix}/"))


def dir_prefixes_overlap(first: str, second: str) -> bool:
    if not first or not second:
        return True
    return is_path_prefix(first, second) or is_path_prefix(second, first)


def glob_patterns_overlap(first: str, second: str) -> bool:
    first = normalize_glob(first)
    second = normalize_glob(second)
    if not first or not second:
        return False
    if first == second:
        return True

    first_sample = glob_sample(first)
    second_sample = glob_sample(second)
    if fnmatch.fnmatchcase(first_sample, second) or fnmatch.fnmatchcase(second_sample, first):
        return True

    first_has_meta = has_glob_meta(first)
    second_has_meta = has_glob_meta(second)
    if not first_has_meta and not second_has_meta:
        return is_path_prefix(first, second) or is_path_prefix(second, first)
    if first_has_meta and second_has_meta:
        return dir_prefixes_overlap(glob_literal_dir_prefix(first), glob_literal_dir_prefix(second))
    if not first_has_meta:
        return fnmatch.fnmatchcase(first, second) or is_path_prefix(first, glob_literal_prefix(second))
    if not second_has_meta:
        return fnmatch.fnmatchcase(second, first) or is_path_prefix(second, glob_literal_prefix(first))
    return False


def terminal_claim_tasks(records: list[dict[str, object]]) -> set[str]:
    terminal_tasks: set[str] = set()
    for record in records:
        record_type = record.get("type")
        if record_type == "task_updated":
            task_id = record.get("id")
            status = record.get("status")
        elif record_type == "task_checkpoint":
            task_id = record.get("task_id")
            status = record.get("status")
        else:
            continue
        if isinstance(task_id, str) and task_id and status in TERMINAL_TASK_STATUSES:
            terminal_tasks.add(task_id)
    return terminal_tasks


def file_claim_conflict_report(records: list[dict[str, object]]) -> dict[str, object]:
    terminal_tasks = terminal_claim_tasks(records)
    claims_by_task: dict[str, list[str]] = {}
    for record in records:
        if record.get("type") != "file_claimed":
            continue
        task_id = record.get("task_id")
        allow = record.get("allow")
        if not isinstance(task_id, str) or not task_id or not isinstance(allow, list):
            continue
        if task_id in terminal_tasks:
            continue
        task_claims = claims_by_task.setdefault(task_id, [])
        task_claims.extend(pattern for pattern in allow if isinstance(pattern, str) and pattern)

    conflicts: list[dict[str, object]] = []
    task_ids = sorted(claims_by_task)
    for left_index, task_a in enumerate(task_ids):
        for task_b in task_ids[left_index + 1 :]:
            overlap = [
                {"allow_a": pattern_a, "allow_b": pattern_b}
                for pattern_a in claims_by_task[task_a]
                for pattern_b in claims_by_task[task_b]
                if glob_patterns_overlap(pattern_a, pattern_b)
            ]
            if overlap:
                conflicts.append({"task_a": task_a, "task_b": task_b, "overlap": overlap})
    return {"ok": not conflicts, "conflicts": conflicts}
