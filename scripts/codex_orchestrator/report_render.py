from __future__ import annotations

from .orchestration_graph import *
from .report_common import *
from .resolution import clears_refs, is_acceptance, is_executable, parse_ref, verifications_by_id


def verification_kind_label(kind: object) -> str:
    if not isinstance(kind, str):
        return "Verification"
    return VERIFICATION_KIND_LABELS.get(kind, kind.replace("_", " ").title())


def record_lines(record: dict[str, object], evidence_id: str = "") -> list[str]:
    result = text_field(record.get("result")) or "unknown"
    label = verification_kind_label(record.get("kind"))
    if evidence_id:
        label = f"{evidence_id} — {label}"
    lines = [f"- **{label}** ({result})"]
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


def typed_review_lines(record: dict[str, object], evidence_id: str = "") -> list[str]:
    result = text_field(record.get("result")) or "unknown"
    kind = text_field(record.get("kind")) or "review"
    label = f"{kind.replace('_', ' ').title()} Review"
    if evidence_id:
        label = f"{evidence_id} — {label}"
    lines = [f"- **{label}** ({result})"]
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
    blocking_findings = record.get("blocking_findings")
    if isinstance(blocking_findings, list):
        rendered_findings: list[str] = []
        for item in blocking_findings:
            if not isinstance(item, dict):
                continue
            finding_id = text_field(item.get("id"))
            claim = text_field(item.get("claim"))
            if not finding_id or not claim:
                continue
            severity = text_field(item.get("severity")) or "P1"
            line = f"    - [{severity}] {finding_id}: {claim}"
            repro_command = text_field(item.get("repro_command"))
            if repro_command:
                line += f" (repro: {inline_code(repro_command)})"
            rendered_findings.append(line)
        if rendered_findings:
            lines.append("  - Blocking Findings:")
            lines.extend(rendered_findings)
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


def resolution_basis_label(basis: str) -> str:
    return basis.replace("_", " ")


def resolution_basis_counts(records: list[dict[str, object]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for record in records:
        basis = text_field(record.get("resolution_basis"))
        if basis:
            counts[basis] = counts.get(basis, 0) + 1
    return counts


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


def render_reproducibility(
    lines: list[str],
    run_meta: dict[str, object] | None,
    completeness: dict[str, object],
) -> None:
    del completeness
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
    lines.append("")


def render_gate_result(lines: list[str], ledger: list[dict[str, object]]) -> None:
    lines.extend(["## Gate Result", ""])
    record = latest_record(ledger, "gate_result")
    if not record:
        lines.extend([GATE_RESULT_PLACEHOLDER, ""])
        return

    ok = gate_result_ok(record)
    ok_text = "unknown" if ok is None else str(ok).lower()
    lines.append(f"- OK: {inline_code(ok_text)}")

    blocking = string_list(record.get("blocking"))
    if blocking:
        lines.append("- Blocking:")
        lines.extend(f"  - {item}" for item in blocking)
    else:
        lines.append("- Blocking: none")

    warnings = string_list(record.get("warnings"))
    if warnings:
        lines.append("- Warnings:")
        lines.extend(f"  - {item}" for item in warnings)
    else:
        lines.append("- Warnings: none")
    lines.append("")


def accepted_risk_records(records: list[dict[str, object]]) -> list[dict[str, object]]:
    return [
        record
        for record in records
        if text_field(record.get("resolution_basis")) in {"accepted_risk", "user_override"}
    ]


def render_accepted_risks_and_overrides(
    lines: list[str],
    consensus_records: list[dict[str, object]],
    ledger: list[dict[str, object]],
) -> bool:
    records = accepted_risk_records(consensus_records)
    if not records:
        return False
    by_id = verifications_by_id(ledger)
    lines.extend(["### Accepted Risks & Overrides", ""])
    for record in records:
        basis = text_field(record.get("resolution_basis"))
        label = "Accepted Risk" if basis == "accepted_risk" else "User Override"
        finding = text_field(record.get("finding") or record.get("summary")) or "Consensus record"
        lines.append(f"- **{label}:** {finding}")
        for ref in clears_refs(record):
            parsed = parse_ref(ref)
            if parsed is None:
                continue
            ref_type, ref_id = parsed
            if ref_type == "verification":
                records_for_id = by_id.get(ref_id, [])
                if len(records_for_id) != 1:
                    lines.append(f"  - Clears {inline_code(ref)} (unknown verification)")
                    continue
                verification = records_for_id[0]
                executable = "yes" if is_executable(verification) else "no"
                acceptance = "yes" if is_acceptance(verification) else "no"
                lines.append(
                    f"  - Clears {inline_code(ref)} (executable: {executable}, acceptance: {acceptance})"
                )
            elif ref_type == "finding":
                lines.append(f"  - Clears {inline_code(ref)}")
    lines.append("")
    return True


def has_change_evidence(ledger: list[dict[str, object]]) -> bool:
    for record in ledger:
        record_type = record.get("type")
        if record_type in {"change", "task"}:
            return True
        if record_type == "task_checkpoint" and string_list(record.get("files_changed")):
            return True
    return False


def has_completed_task(ledger: list[dict[str, object]]) -> bool:
    return any(
        record.get("type") in {"task", "task_created", "task_updated", "task_checkpoint"}
        and record.get("status") == "complete"
        for record in ledger
    )


def strict_report_missing_evidence(
    *,
    state: dict[str, object],
    ledger: list[dict[str, object]],
    report: str,
) -> list[str]:
    del state
    missing: list[str] = []
    if RUN_META_PLACEHOLDER in report:
        missing.append("run metadata")
    if ORCHESTRATION_GRAPH_PLACEHOLDER in report:
        missing.append("orchestration graph")
    if CHANGES_PLACEHOLDER in report and not has_change_evidence(ledger):
        missing.append("changes evidence")
    if REVIEW_PLACEHOLDER in report:
        missing.append("review notes")
    if CONSENSUS_PLACEHOLDER in report:
        missing.append("consensus or review evidence")
    if GATE_RESULT_PLACEHOLDER in report and has_completed_task(ledger):
        missing.append("gate result")
    return missing


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
    basis_counts = resolution_basis_counts(consensus_records)
    evidence_ids = evidence_record_ids(ledger)

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
            f"- Reviews: {len(all_review_records)}",
            f"- Consensus: {consensus_outcome_tally(consensus_records)}",
        ])
        accepted_risks = basis_counts.get("accepted_risk", 0)
        user_overrides = basis_counts.get("user_override", 0)
        if accepted_risks:
            lines.append(f"- Accepted Risks: {accepted_risks}")
        if user_overrides:
            lines.append(f"- User Overrides: {user_overrides}")
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

    render_orchestration_graph(lines, state, ledger)

    lines.extend(["## Consensus", ""])
    wrote_consensus_content = False
    manual_review = manual_review_section(existing_report)
    manual_consensus = manual_consensus_section(existing_report)
    if manual_review:
        lines.extend(["### Review Notes", "", manual_review, ""])
        wrote_consensus_content = True
    if manual_consensus:
        lines.extend([manual_consensus, ""])
        wrote_consensus_content = True
    if evidence_records:
        lines.extend(["### Verification Checks", ""])
        for record in evidence_records:
            lines.extend(record_lines(record, evidence_ids.get(id(record), "")))
        lines.append("")
        wrote_consensus_content = True
    if all_review_records:
        lines.extend(["### Reviews", ""])
        for record in review_records:
            lines.extend(record_lines(record, evidence_ids.get(id(record), "")))
        for record in typed_review_records:
            lines.extend(typed_review_lines(record, evidence_ids.get(id(record), "")))
        lines.append("")
        wrote_consensus_content = True
    if consensus_records:
        if render_accepted_risks_and_overrides(lines, consensus_records, ledger):
            wrote_consensus_content = True
        lines.extend(["### Decisions", ""])
        for record in consensus_records:
            finding = text_field(record.get("finding") or record.get("summary")) or "Consensus record"
            lines.append(f"- **Finding:** {finding}")
            root_cause = text_field(record.get("root_cause"))
            if root_cause:
                lines.append(f"  - **Root Cause:** {root_cause}")
            lines.append(f"  - **Resolution:** {text_field(record.get('resolution')) or 'Not recorded.'}")
            lines.append(f"  - **Outcome:** {consensus_outcome_label(consensus_outcome(record))}")
            basis = text_field(record.get("resolution_basis"))
            if basis:
                lines.append(f"  - **Basis:** {resolution_basis_label(basis)}")
            clears = string_list(record.get("clears"))
            if clears:
                lines.append("  - **Clears:**")
                lines.extend(f"    - {inline_code(item)}" for item in clears)
            evidence_refs = string_list(record.get("evidence_refs"))
            if evidence_refs:
                lines.append("  - **Evidence Refs:**")
                lines.extend(f"    - {inline_code(item)}" for item in evidence_refs)
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

    render_gate_result(lines, ledger)

    lines.extend(["## Risks / Follow-ups", ""])
    lines.extend(f"- {item}" for item in open_risks) if open_risks else lines.append(RISKS_PLACEHOLDER)
    return "\n".join(lines) + "\n"
