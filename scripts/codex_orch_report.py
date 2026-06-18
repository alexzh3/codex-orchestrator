from __future__ import annotations

import json

from codex_orch_contract import (
    ALLOWED_VERIFICATION_RESULTS,
    CONSENSUS_OUTCOME_ORDER,
    LEGACY_CONSENSUS_STATUS_OUTCOMES,
    TASK_STATUS_ORDER,
)

CONSENSUS_PLACEHOLDER = "No consensus decisions recorded."
REVIEW_PLACEHOLDER = "No review notes recorded."
SUMMARY_PLACEHOLDER = "No authored summary recorded."
CHANGES_PLACEHOLDER = "No authored changes recorded."
EVIDENCE_PLACEHOLDER = "No evidence recorded."
RISKS_PLACEHOLDER = "No unresolved risks or follow-ups recorded."
REVIEW_KINDS = {"manual_review", "git_diff"}
SUMMARY_OPEN_ITEM_LIMIT = 140
TASK_RISK_STATUSES = {"blocked", "failed"}
UNRESOLVED_VERIFICATION_RESULTS = {"failed", "inconclusive", "needs_human_review"}
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
    evidence_records = [record for record in verifications if record.get("kind") not in REVIEW_KINDS]
    consensus_records = [record for record in ledger if record.get("type") == "consensus"]
    task_records = [record for record in ledger if record.get("type") == "task"]
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
        ])
        if task_records:
            lines.append(f"- Changes: {len(task_records)} ({task_status_tally(task_records)})")
            lines.extend(f"  - {truncate_summary_item(task_title(record))}" for record in task_records)
        else:
            lines.append("- Changes: none")
        lines.extend([
            f"- Evidence: {verification_tally(evidence_records)}",
            f"- Reviews: {len(review_records)}",
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

    lines.extend(["## Changes", ""])
    authored_changes = authored_changes_section(existing_report)
    if authored_changes:
        lines.extend([authored_changes, ""])
    elif task_records:
        lines.extend([CHANGES_PLACEHOLDER, "", "### Ledger Records", ""])
        for record in task_records:
            lines.append(f"- **{task_title(record)}** ({text_field(record.get('status')) or 'unknown'})")
            for field, label in (("owner", "Owner"), ("notes", "Notes")):
                value = text_field(record.get(field))
                if value:
                    lines.append(f"  - {label}: {value}")
        lines.append("")
    else:
        lines.extend([CHANGES_PLACEHOLDER, ""])

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
    if review_records:
        lines.extend(["### Reviews", ""])
        for record in review_records:
            lines.extend(record_lines(record))
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
