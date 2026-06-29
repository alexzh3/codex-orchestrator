from __future__ import annotations

import json

from codex_orch_contract import (
    ALLOWED_VERIFICATION_RESULTS,
    CONSENSUS_OUTCOME_ORDER,
    LEGACY_CONSENSUS_STATUS_OUTCOMES,
    RUN_META_CONFIG_FIELDS,
    TASK_STATUS_ORDER,
)

CONSENSUS_PLACEHOLDER = "No consensus decisions recorded."
REVIEW_PLACEHOLDER = "No review notes recorded."
SUMMARY_PLACEHOLDER = "No authored summary recorded."
CHANGES_PLACEHOLDER = "No authored changes recorded."
EVIDENCE_PLACEHOLDER = "No evidence recorded."
RISKS_PLACEHOLDER = "No unresolved risks or follow-ups recorded."
RUN_META_PLACEHOLDER = "No run metadata recorded."
TASK_GRAPH_PLACEHOLDER = "No task graph records recorded."
REVIEW_KINDS = {"manual_review", "git_diff"}
FINAL_REVIEW_KINDS = {"review", "manual_review", "git_diff"}
SUMMARY_OPEN_ITEM_LIMIT = 140
TASK_RISK_STATUSES = {"blocked", "failed"}
UNRESOLVED_VERIFICATION_RESULTS = {"failed", "inconclusive", "needs_human_review"}
COMPLETENESS_COMPONENTS = (
    ("run_meta_present", "run_meta present", 0.15),
    ("tasks_listed", "all tasks listed", 0.15),
    ("changed_files_attributed", "all changed files attributed", 0.15),
    ("verification_records_complete", "verification records complete", 0.15),
    ("final_review_present", "final review present", 0.15),
    ("risks_reflect_failed_checks", "risks reflect failed/inconclusive checks", 0.10),
    ("gate_result_present", "gate result present", 0.10),
    ("prompt_log_pairs_complete", "prompt/log pairs complete", 0.05),
)
CONSENSUS_OUTCOME_LABELS = {
    "consensus": "consensus",
    "claude_decision": "Claude decision",
    "user_action_required": "user action required",
}
UNRESOLVED_CONSENSUS_OUTCOMES = {"user_action_required"}
VERIFICATION_KIND_LABELS = {
    "artifact_check": "Artifact check",
    "benchmark": "Benchmark",
    "build": "Build",
    "custom": "Custom check",
    "git_diff": "Git diff review",
    "lint": "Lint",
    "manual_review": "Manual / agent review",
    "screenshot": "Screenshot check",
    "test": "Test",
    "typecheck": "Typecheck",
}


def report_section(text: str, heading: str, default: str) -> str:
    marker = f"## {heading}"
    lines = text.splitlines()
    start_index: int | None = None
    for index, line in enumerate(lines):
        if line.strip() == marker:
            start_index = index + 1
            break
    if start_index is None:
        return default
    end_index = len(lines)
    for index in range(start_index, len(lines)):
        if lines[index].startswith("## "):
            end_index = index
            break
    section = "\n".join(lines[start_index:end_index]).strip()
    return section or default


def manual_consensus_section(text: str) -> str:
    section = report_section(text, "Consensus", "")
    for generated_marker in ("### Reviews", "### Decisions", "### Ledger Records"):
        if generated_marker in section:
            section = section.split(generated_marker, 1)[0].strip()
    return "\n".join(
        line for line in section.splitlines() if line.strip() != CONSENSUS_PLACEHOLDER
    ).strip()


def is_old_generated_summary(section: str) -> bool:
    lines = [line.strip() for line in section.splitlines() if line.strip()]
    return bool(lines) and lines[0].startswith("Run ID:") and any(
        line.startswith("- Acceptance:") for line in lines
    )


def authored_summary_section(text: str) -> str:
    section = report_section(text, "Summary", "")
    if "### Generated Digest" in section:
        section = section.split("### Generated Digest", 1)[0].strip()
    if is_old_generated_summary(section):
        return ""
    return "\n".join(
        line for line in section.splitlines() if line.strip() != SUMMARY_PLACEHOLDER
    ).strip()


def is_old_generated_changes(section: str) -> bool:
    lines = [line.strip() for line in section.splitlines() if line.strip()]
    if not lines:
        return False
    if lines == ["No changes recorded."]:
        return True
    return lines[0].startswith("- **") and all(
        line.startswith("- **") or line.startswith("- Owner:") or line.startswith("- Notes:")
        for line in lines
    )


def authored_changes_section(text: str) -> str:
    section = report_section(text, "Changes", "")
    if "### Ledger Records" in section:
        section = section.split("### Ledger Records", 1)[0].strip()
    if is_old_generated_changes(section):
        return ""
    return "\n".join(
        line
        for line in section.splitlines()
        if line.strip() not in {CHANGES_PLACEHOLDER, "No changes recorded."}
    ).strip()


def manual_review_section(text: str) -> str:
    section = report_section(text, "Review", "")
    generated_marker = "### Recorded Reviews"
    if generated_marker in section:
        section = section.split(generated_marker, 1)[0].strip()
    return "\n".join(
        line for line in section.splitlines() if line.strip() != REVIEW_PLACEHOLDER
    ).strip()


def text_field(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        return json.dumps(value, sort_keys=True)
    return str(value)


def inline_code(value: object) -> str:
    text = str(value).replace("`", "\\`")
    return f"`{text}`"


def clamp_unit(value: float) -> float:
    return max(0.0, min(1.0, value))


def string_list(value: object) -> list[str]:
    if isinstance(value, str) and value:
        return [value]
    if isinstance(value, list):
        return [item for item in value if isinstance(item, str) and item]
    return []


def latest_record(ledger: list[dict[str, object]], record_type: str) -> dict[str, object] | None:
    records = [record for record in ledger if record.get("type") == record_type]
    return records[-1] if records else None


def is_final_review_verification(record: dict[str, object]) -> bool:
    return record.get("type") == "verification" and record.get("kind") in FINAL_REVIEW_KINDS


def is_passed_typed_review(record: dict[str, object]) -> bool:
    return record.get("type") == "review" and record.get("result") == "passed"


def is_final_review_record(record: dict[str, object]) -> bool:
    return is_final_review_verification(record) or is_passed_typed_review(record)


def is_dispatch_record(record: dict[str, object]) -> bool:
    return record.get("type") in {"dispatch_started", "session_dispatch"}


def task_completion_ratio(task_records: list[dict[str, object]]) -> float:
    if not task_records:
        return 0.0
    complete = 0
    for record in task_records:
        if all(text_field(record.get(field)) for field in ("id", "title", "status")):
            complete += 1
    return complete / len(task_records)


def changed_file_attribution_ratio(
    ledger: list[dict[str, object]],
    task_records: list[dict[str, object]],
) -> float:
    task_ids = {text_field(record.get("id")) for record in task_records if text_field(record.get("id"))}
    total_files = 0
    attributed_files = 0
    for record in ledger:
        if record.get("type") != "task_checkpoint":
            continue
        files = string_list(record.get("files_changed"))
        if not files:
            continue
        total_files += len(files)
        task_ref = text_field(record.get("task_id"))
        if not task_ref or (task_ids and task_ref not in task_ids):
            continue
        attributed_files += len(files)
    if total_files == 0:
        return 1.0
    return attributed_files / total_files


def verification_completion_ratio(verification_records: list[dict[str, object]]) -> float:
    if not verification_records:
        return 0.0
    complete = 0
    for record in verification_records:
        if all(text_field(record.get(field)) for field in ("kind", "result", "recorded_at", "summary")):
            complete += 1
    return complete / len(verification_records)


def risks_reflect_failed_checks_ratio(verification_records: list[dict[str, object]]) -> float:
    if not verification_records:
        return 0.0
    unresolved = [
        record
        for record in verification_records
        if text_field(record.get("result")) in UNRESOLVED_VERIFICATION_RESULTS
    ]
    if not unresolved:
        return 1.0
    reflected = unresolved_items([], unresolved, [], [])
    return len(reflected) / len(unresolved)


def prompt_log_pair_ratio(ledger: list[dict[str, object]]) -> float:
    dispatches = [record for record in ledger if is_dispatch_record(record)]
    if not dispatches:
        return 1.0
    complete = 0
    for record in dispatches:
        if text_field(record.get("prompt_path")) and text_field(record.get("log_path")):
            complete += 1
    return complete / len(dispatches)


def prompt_log_pairs_complete(ledger: list[dict[str, object]]) -> bool:
    return prompt_log_pair_ratio(ledger) == 1.0


def gate_result_present(ledger: list[dict[str, object]]) -> bool:
    return any(record.get("type") == "gate_result" for record in ledger)


def task_records_for_score(ledger: list[dict[str, object]]) -> list[dict[str, object]]:
    task_created_records = [record for record in ledger if record.get("type") == "task_created"]
    if task_created_records:
        return task_created_records
    return [record for record in ledger if record.get("type") == "task"]


def has_work_evidence(ledger: list[dict[str, object]]) -> bool:
    evidence_types = {
        "consensus",
        "dispatch_started",
        "file_claimed",
        "gate_result",
        "review",
        "session_dispatch",
        "task",
        "task_checkpoint",
        "task_created",
        "task_updated",
        "verification",
    }
    return any(record.get("type") in evidence_types for record in ledger)


def report_completeness_score(state: dict[str, object], ledger: list[dict[str, object]]) -> dict[str, object]:
    del state
    run_meta = latest_record(ledger, "run_meta")
    task_records = task_records_for_score(ledger)
    verification_records = [record for record in ledger if record.get("type") == "verification"]
    has_evidence = has_work_evidence(ledger)
    ratios = {
        "run_meta_present": 1.0 if run_meta else 0.0,
        "tasks_listed": task_completion_ratio(task_records),
        "changed_files_attributed": changed_file_attribution_ratio(ledger, task_records) if has_evidence else 0.0,
        "verification_records_complete": verification_completion_ratio(verification_records),
        "final_review_present": 1.0 if any(is_final_review_record(record) for record in ledger) else 0.0,
        "risks_reflect_failed_checks": risks_reflect_failed_checks_ratio(verification_records),
        "gate_result_present": 1.0 if gate_result_present(ledger) else 0.0,
        "prompt_log_pairs_complete": prompt_log_pair_ratio(ledger) if has_evidence else 0.0,
    }
    components: dict[str, dict[str, object]] = {}
    for key, label, weight in COMPLETENESS_COMPONENTS:
        score = clamp_unit(float(ratios.get(key, 0.0)))
        earned = round(weight * score, 4)
        components[key] = {
            "label": label,
            "weight": weight,
            "score": round(score, 4),
            "earned": earned,
        }
    total = round(sum(float(component["earned"]) for component in components.values()), 4)
    return {"total": total, "components": components}


def score_total(score: dict[str, object]) -> float:
    total = score.get("total")
    return float(total) if isinstance(total, (int, float)) else 0.0


def score_component_lines(score: dict[str, object]) -> list[str]:
    components = score.get("components")
    if not isinstance(components, dict):
        return []
    lines: list[str] = []
    for key, _, _ in COMPLETENESS_COMPONENTS:
        component = components.get(key)
        if not isinstance(component, dict):
            continue
        label = text_field(component.get("label")) or key
        earned = float(component.get("earned") or 0.0)
        weight = float(component.get("weight") or 0.0)
        lines.append(f"  - {label}: {earned:.2f}/{weight:.2f}")
    return lines


def verification_kind_label(kind: object) -> str:
    if not isinstance(kind, str):
        return "Verification"
    return VERIFICATION_KIND_LABELS.get(kind, kind.replace("_", " ").title())


def record_lines(record: dict[str, object]) -> list[str]:
    result = text_field(record.get("result")) or "unknown"
    lines = [f"- **{verification_kind_label(record.get('kind'))}** ({result})"]
    for field, label in (("summary", "Summary"), ("command", "Command"), ("notes", "Notes")):
        value = text_field(record.get(field))
        if not value:
            continue
        value = inline_code(value) if field == "command" else value
        lines.append(f"  - {label}: {value}")
    if record.get("exit_code") is not None:
        lines.append(f"  - Exit Code: {inline_code(record.get('exit_code'))}")
    artifacts = record.get("artifacts")
    if isinstance(artifacts, list):
        artifact_items = [text_field(item) for item in artifacts]
        artifact_items = [item for item in artifact_items if item]
        if artifact_items:
            lines.append("  - Artifacts:")
            lines.extend(f"    - {inline_code(item)}" for item in artifact_items)
    return lines


def typed_review_lines(record: dict[str, object]) -> list[str]:
    result = text_field(record.get("result")) or "unknown"
    kind = text_field(record.get("kind")) or "review"
    lines = [f"- **{kind.replace('_', ' ').title()} Review** ({result})"]
    for field, label in (
        ("reviewer", "Reviewer"),
        ("summary", "Summary"),
        ("command", "Command"),
        ("prompt_path", "Prompt"),
        ("log_path", "Log"),
    ):
        value = text_field(record.get(field))
        if not value:
            continue
        value = inline_code(value) if field in {"command", "prompt_path", "log_path"} else value
        lines.append(f"  - {label}: {value}")
    findings = string_list(record.get("findings"))
    if findings:
        lines.append("  - Findings:")
        lines.extend(f"    - {finding}" for finding in findings)
    return lines


def verification_tally(records: list[dict[str, object]]) -> str:
    if not records:
        return "none recorded"
    counts: dict[str, int] = {}
    for record in records:
        result = text_field(record.get("result")) or "unknown"
        counts[result] = counts.get(result, 0) + 1
    ordered_results = [result for result in ALLOWED_VERIFICATION_RESULTS if result in counts]
    ordered_results.extend(sorted(result for result in counts if result not in ALLOWED_VERIFICATION_RESULTS))
    return ", ".join(f"{counts[result]} {result}" for result in ordered_results)


def consensus_outcome(record: dict[str, object]) -> str:
    outcome = text_field(record.get("outcome"))
    if outcome:
        return outcome
    legacy_status = text_field(record.get("status"))
    if legacy_status:
        return LEGACY_CONSENSUS_STATUS_OUTCOMES.get(legacy_status, legacy_status)
    return "unknown"


def consensus_outcome_label(outcome: str) -> str:
    return CONSENSUS_OUTCOME_LABELS.get(outcome, outcome.replace("_", " "))


def consensus_outcome_tally(records: list[dict[str, object]]) -> str:
    if not records:
        return "none"
    counts: dict[str, int] = {}
    for record in records:
        outcome = consensus_outcome(record)
        counts[outcome] = counts.get(outcome, 0) + 1
    ordered_outcomes = [outcome for outcome in CONSENSUS_OUTCOME_ORDER if outcome in counts]
    ordered_outcomes.extend(sorted(outcome for outcome in counts if outcome not in CONSENSUS_OUTCOME_ORDER))
    return ", ".join(
        f"{counts[outcome]} {consensus_outcome_label(outcome)}" for outcome in ordered_outcomes
    )


def task_status_tally(records: list[dict[str, object]]) -> str:
    if not records:
        return "none"
    counts: dict[str, int] = {}
    for record in records:
        status = text_field(record.get("status")) or "unknown"
        counts[status] = counts.get(status, 0) + 1
    parts = [f"{counts[status]} {status}" for status in TASK_STATUS_ORDER if status in counts]
    parts.extend(f"{counts[status]} {status}" for status in sorted(counts) if status not in TASK_STATUS_ORDER)
    return ", ".join(parts) if parts else "none"


def task_title(record: dict[str, object]) -> str:
    return text_field(record.get("title")) or text_field(record.get("id")) or "Task record"


def truncate_summary_item(text: str) -> str:
    if len(text) <= SUMMARY_OPEN_ITEM_LIMIT:
        return text
    return text[: SUMMARY_OPEN_ITEM_LIMIT - 1].rstrip() + "…"


def brief_string_list(value: object, *, code: bool = False, limit: int = 3) -> str:
    items = string_list(value)
    if not items:
        return ""
    rendered: list[str] = []
    for item in items[:limit]:
        text = inline_code(item) if code else truncate_summary_item(item)
        rendered.append(text)
    remaining = len(items) - limit
    if remaining > 0:
        rendered.append(f"+{remaining} more")
    return ", ".join(rendered)


def unresolved_items(
    warnings: list[str],
    verification_records: list[dict[str, object]],
    consensus_records: list[dict[str, object]],
    task_records: list[dict[str, object]],
) -> list[str]:
    items = list(warnings)
    for record in verification_records:
        result = text_field(record.get("result")) or "unknown"
        if result in UNRESOLVED_VERIFICATION_RESULTS:
            kind = verification_kind_label(record.get("kind"))
            summary = text_field(record.get("summary")) or "No summary recorded."
            items.append(f"{kind} ({result}): {summary}")
    for record in consensus_records:
        outcome = consensus_outcome(record)
        requires_user = record.get("requires_user") is True
        if outcome in UNRESOLVED_CONSENSUS_OUTCOMES or requires_user:
            finding = text_field(record.get("finding") or record.get("summary")) or "Consensus record"
            items.append(f"{finding} ({consensus_outcome_label(outcome)})")
    for record in task_records:
        status = text_field(record.get("status")) or "unknown"
        if status in TASK_RISK_STATUSES:
            items.append(f"{task_title(record)} ({status})")
    return items


def acceptance_decision(status: object, open_risks: list[str]) -> str:
    if status == "accepted":
        if open_risks:
            return f"Accepted, but {len(open_risks)} unresolved item(s) remain — see Risks / Follow-ups."
        return "Accepted based on recorded evidence."
    if status == "rejected":
        return "Rejected based on recorded evidence."
    return "No acceptance decision recorded; this run needs review."


def metadata_value(value: object) -> str:
    text = text_field(value)
    return inline_code(text) if text else "not recorded"


def render_task_records(lines: list[str], task_records: list[dict[str, object]]) -> None:
    lines.extend(["### Ledger Records", ""])
    for record in task_records:
        lines.append(f"- **{task_title(record)}** ({text_field(record.get('status')) or 'unknown'})")
        for field, label in (("owner", "Owner"), ("notes", "Notes")):
            value = text_field(record.get(field))
            if value:
                lines.append(f"  - {label}: {value}")
    lines.append("")


def task_graph_records(ledger: list[dict[str, object]]) -> list[dict[str, object]]:
    tasks: dict[str, dict[str, object]] = {}
    order: list[str] = []

    def task_for(task_id: str) -> dict[str, object]:
        if task_id not in tasks:
            tasks[task_id] = {"id": task_id}
            order.append(task_id)
        return tasks[task_id]

    for record in ledger:
        record_type = record.get("type")
        if record_type == "task_created":
            task_id = text_field(record.get("id"))
            if not task_id:
                continue
            task = task_for(task_id)
            for field in ("title", "status", "owner"):
                value = text_field(record.get(field))
                if value:
                    task[field] = value
            for field in ("files_allowed", "acceptance"):
                values = string_list(record.get(field))
                if values:
                    task[field] = values
        elif record_type == "task_updated":
            task_id = text_field(record.get("id"))
            if not task_id:
                continue
            task = task_for(task_id)
            status = text_field(record.get("status"))
            if status:
                task["status"] = status
        elif record_type == "task_checkpoint":
            task_id = text_field(record.get("task_id"))
            if not task_id:
                continue
            task = task_for(task_id)
            task["latest_checkpoint"] = record
            task.setdefault("owner", text_field(record.get("agent")))
            task.setdefault("status", text_field(record.get("status")))

    return [tasks[task_id] for task_id in order]


def render_task_graph(lines: list[str], ledger: list[dict[str, object]]) -> None:
    lines.extend(["## Task Graph", ""])
    tasks = task_graph_records(ledger)
    if not tasks:
        lines.extend([TASK_GRAPH_PLACEHOLDER, ""])
        return

    for task in tasks:
        task_id = text_field(task.get("id")) or "unknown"
        title = text_field(task.get("title")) or task_id
        status = text_field(task.get("status")) or "unknown"
        lines.append(f"- **{task_id}**: {title} ({status})")
        lines.append(f"  - Owner: {text_field(task.get('owner')) or 'not recorded'}")
        lines.append(
            f"  - Files allowed: {brief_string_list(task.get('files_allowed'), code=True) or 'not recorded'}"
        )
        lines.append(f"  - Acceptance: {brief_string_list(task.get('acceptance')) or 'not recorded'}")
        checkpoint = task.get("latest_checkpoint")
        if isinstance(checkpoint, dict):
            checkpoint_status = text_field(checkpoint.get("status")) or "unknown"
            checkpoint_summary = text_field(checkpoint.get("summary")) or "No summary recorded."
            lines.append(f"  - Latest checkpoint: {checkpoint_status} - {checkpoint_summary}")
            files_changed = brief_string_list(checkpoint.get("files_changed"), code=True)
            lines.append(f"  - Files changed: {files_changed or 'none'}")
        else:
            lines.append("  - Latest checkpoint: not recorded")
            lines.append("  - Files changed: none")
    lines.append("")


def render_reproducibility(
    lines: list[str],
    run_meta: dict[str, object] | None,
    completeness: dict[str, object],
) -> None:
    lines.extend(["## Reproducibility", ""])
    if run_meta:
        for field, label in (
            ("plugin_version", "Plugin Version"),
            ("plugin_git_sha", "Plugin Git SHA"),
            ("protocol_version", "Protocol Version"),
            ("schema_version", "Schema Version"),
            ("repo_commit", "Repo Commit"),
            ("benchmark_suite", "Benchmark Suite"),
            ("benchmark_case_id", "Benchmark Case"),
        ):
            lines.append(f"- {label}: {metadata_value(run_meta.get(field))}")
        config = run_meta.get("config")
        if isinstance(config, dict):
            lines.append("- Config:")
            for field in RUN_META_CONFIG_FIELDS:
                lines.append(f"  - {field}: {metadata_value(config.get(field))}")
    else:
        lines.append(RUN_META_PLACEHOLDER)
    lines.extend(["", "### Report Completeness", ""])
    lines.append(f"- Report Completeness: {score_total(completeness):.2f}")
    lines.extend(score_component_lines(completeness))
    lines.append("")


def render_report(
    *,
    state: dict[str, object],
    ledger: list[dict[str, object]],
    existing_report: str,
    warnings: list[str],
    generated_at: str,
) -> str:
    verifications = [record for record in ledger if record.get("type") == "verification"]
    review_records = [record for record in verifications if record.get("kind") in REVIEW_KINDS]
    typed_review_records = [record for record in ledger if record.get("type") == "review"]
    all_review_records = [*review_records, *typed_review_records]
    evidence_records = [record for record in verifications if record.get("kind") not in REVIEW_KINDS]
    consensus_records = [record for record in ledger if record.get("type") == "consensus"]
    task_records = [record for record in ledger if record.get("type") == "task"]
    run_meta = latest_record(ledger, "run_meta")
    completeness = report_completeness_score(state, ledger)
    open_risks = unresolved_items(warnings, verifications, consensus_records, task_records)
    sessions = state.get("sessions") if isinstance(state.get("sessions"), list) else []

    lines = ["# Report", "", "## Summary", ""]
    authored_summary = authored_summary_section(existing_report)
    if authored_summary:
        lines.extend([authored_summary, ""])
    else:
        lines.extend([
            SUMMARY_PLACEHOLDER,
            "",
            "### Generated Digest",
            "",
            f"- Run ID: {state.get('run_id')}",
            f"- Status: {state.get('status')}",
            f"- Generated at: {generated_at}",
            f"- Acceptance: {acceptance_decision(state.get('status'), open_risks)}",
            f"- Report Completeness: {score_total(completeness):.2f}",
        ])
        if task_records:
            lines.append(f"- Changes: {len(task_records)} ({task_status_tally(task_records)})")
            lines.extend(f"  - {truncate_summary_item(task_title(record))}" for record in task_records)
        else:
            lines.append("- Changes: none")
        lines.extend([
            f"- Evidence: {verification_tally(evidence_records)}",
            f"- Reviews: {len(all_review_records)}",
            f"- Consensus: {consensus_outcome_tally(consensus_records)}",
        ])
        if sessions:
            lines.append(f"- Sessions: {len(sessions)}")
        if open_risks:
            lines.append(f"- Open items ({len(open_risks)}):")
            lines.extend(f"  - {truncate_summary_item(item)}" for item in open_risks)
        else:
            lines.append("- Open items: none")
        lines.append("")

    render_reproducibility(lines, run_meta, completeness)

    lines.extend(["## Changes", ""])
    authored_changes = authored_changes_section(existing_report)
    if authored_changes:
        lines.extend([authored_changes, ""])
        if task_records:
            render_task_records(lines, task_records)
    elif task_records:
        lines.extend([CHANGES_PLACEHOLDER, ""])
        render_task_records(lines, task_records)
    else:
        lines.extend([CHANGES_PLACEHOLDER, ""])

    render_task_graph(lines, ledger)

    lines.extend(["## Evidence", ""])
    if evidence_records:
        for record in evidence_records:
            lines.extend(record_lines(record))
    else:
        lines.append(EVIDENCE_PLACEHOLDER)

    lines.extend(["", "## Consensus", ""])
    wrote_consensus_content = False
    manual_review = manual_review_section(existing_report)
    manual_consensus = manual_consensus_section(existing_report)
    if manual_review:
        lines.extend(["### Review Notes", "", manual_review, ""])
        wrote_consensus_content = True
    if manual_consensus:
        lines.extend([manual_consensus, ""])
        wrote_consensus_content = True
    if all_review_records:
        lines.extend(["### Reviews", ""])
        for record in review_records:
            lines.extend(record_lines(record))
        for record in typed_review_records:
            lines.extend(typed_review_lines(record))
        lines.append("")
        wrote_consensus_content = True
    if consensus_records:
        lines.extend(["### Decisions", ""])
        for record in consensus_records:
            finding = text_field(record.get("finding") or record.get("summary")) or "Consensus record"
            lines.append(f"- **Finding:** {finding}")
            root_cause = text_field(record.get("root_cause"))
            if root_cause:
                lines.append(f"  - **Root Cause:** {root_cause}")
            lines.append(f"  - **Resolution:** {text_field(record.get('resolution')) or 'Not recorded.'}")
            lines.append(f"  - **Outcome:** {consensus_outcome_label(consensus_outcome(record))}")
            risk_level = text_field(record.get("risk_level"))
            if risk_level:
                lines.append(f"  - **Risk Level:** {risk_level}")
            if record.get("requires_user") is not None:
                requires_user = "yes" if record.get("requires_user") is True else "no"
                lines.append(f"  - **Requires User:** {requires_user}")
            evidence = record.get("evidence")
            if isinstance(evidence, list):
                evidence_items = [text_field(item) for item in evidence]
                evidence_items = [item for item in evidence_items if item]
                if evidence_items:
                    lines.append("  - **Evidence:**")
                    lines.extend(f"    - {item}" for item in evidence_items)
            else:
                evidence_text = text_field(evidence)
                if evidence_text:
                    lines.append(f"  - **Evidence:** {evidence_text}")
        lines.append("")
        wrote_consensus_content = True
    if not wrote_consensus_content:
        lines.extend([CONSENSUS_PLACEHOLDER, ""])

    lines.extend(["## Risks / Follow-ups", ""])
    lines.extend(f"- {item}" for item in open_risks) if open_risks else lines.append(RISKS_PLACEHOLDER)
    return "\n".join(lines) + "\n"
