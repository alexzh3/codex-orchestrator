from __future__ import annotations

import re

from .report_common import *
from .resolution import parse_ref


MERMAID_LABEL_LIMIT = 60


def brief_string_list(value: object, *, code: bool = False, limit: int = 3) -> str:
    items = string_list(value)
    if not items:
        return ""
    rendered: list[str] = []
    for item in items[:limit]:
        text = inline_code(item) if code else truncate_graph_item(item)
        rendered.append(text)
    remaining = len(items) - limit
    if remaining > 0:
        rendered.append(f"+{remaining} more")
    return ", ".join(rendered)


def truncate_graph_item(text: str, limit: int = SUMMARY_OPEN_ITEM_LIMIT) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def mermaid_label(value: object, *, limit: int = MERMAID_LABEL_LIMIT) -> str:
    text = text_field(value)
    text = (
        text.replace('"', "'")
        .replace("|", "/")
        .replace("`", "'")
        .replace("<", "(")
        .replace(">", ")")
    )
    text = " ".join(text.split())
    if len(text) > limit:
        text = text[: limit - 1].rstrip() + "…"
    return text


def mermaid_node_label(parts: list[str]) -> str:
    return "<br/>".join(label for part in parts if (label := mermaid_label(part)))


def is_hub_agent(name: object) -> bool:
    return text_field(name).strip().casefold() in {"claude", "claude-code"}


def graph_task_label(task: dict[str, object] | None, task_id: str) -> str:
    if task is None:
        return task_id
    return text_field(task.get("title")) or text_field(task.get("goal")) or task_id


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
            for field in ("title", "status", "owner", "goal"):
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


def graph_consensus_outcome(record: dict[str, object]) -> str:
    outcome = text_field(record.get("outcome"))
    if outcome:
        return outcome
    legacy_status = text_field(record.get("status"))
    if legacy_status:
        return LEGACY_CONSENSUS_STATUS_OUTCOMES.get(legacy_status, legacy_status)
    return "unknown"


def graph_slug(value: object) -> str:
    slug = re.sub(r"[^0-9A-Za-z]", "_", mermaid_label(value, limit=120)).strip("_")
    return slug.upper() or "UNKNOWN"


def task_node_id(task_id: str) -> str:
    slug = graph_slug(task_id)
    if re.fullmatch(r"T[0-9A-Z_]*", slug):
        return slug
    return f"T_{slug}"


def collect_agent_info(
    state: dict[str, object],
    ledger: list[dict[str, object]],
    tasks: list[dict[str, object]],
) -> tuple[list[str], dict[str, dict[str, object]]]:
    sessions = state.get("sessions") if isinstance(state.get("sessions"), list) else []
    agent_order: list[str] = []
    agent_info: dict[str, dict[str, object]] = {}

    def ensure_agent(name: object) -> str:
        agent = text_field(name)
        if not agent or is_hub_agent(agent):
            return ""
        if agent not in agent_info:
            agent_info[agent] = {
                "mode": "",
                "status": "",
                "model": "",
                "reasoning_effort": "",
                "has_session": False,
            }
            agent_order.append(agent)
        return agent

    for session in sessions:
        if not isinstance(session, dict):
            continue
        agent = ensure_agent(session.get("name"))
        if not agent:
            continue
        info = agent_info[agent]
        info["mode"] = text_field(session.get("mode"))
        info["status"] = text_field(session.get("status"))
        info["has_session"] = True

    for task in tasks:
        ensure_agent(task.get("owner"))

    for record in ledger:
        record_type = record.get("type")
        if record_type == "dispatch_started":
            agent = ensure_agent(record.get("agent"))
            if not agent:
                continue
            info = agent_info[agent]
            if not info.get("has_session") and not text_field(info.get("mode")):
                info["mode"] = text_field(record.get("mode"))
            for field in ("model", "reasoning_effort"):
                if not text_field(info.get(field)):
                    info[field] = text_field(record.get(field))
        elif record_type in {"dispatch_completed", "task_checkpoint"}:
            agent = ensure_agent(record.get("agent"))
            status = text_field(record.get("status"))
            if agent and status and not agent_info[agent].get("has_session"):
                agent_info[agent]["status"] = status
        elif record_type == "review":
            ensure_agent(record.get("reviewer"))

    return agent_order, agent_info


def agent_node_ids(agent_order: list[str]) -> dict[str, str]:
    node_ids: dict[str, str] = {}
    used: set[str] = {"A_CLAUDE"}
    for agent in agent_order:
        base = f"A_{graph_slug(agent)}"
        node_id = base
        suffix = 2
        while node_id in used:
            node_id = f"{base}_{suffix}"
            suffix += 1
        used.add(node_id)
        node_ids[agent] = node_id
    return node_ids


def agent_node_id(agent: object, node_ids: dict[str, str]) -> str:
    if is_hub_agent(agent):
        return "A_CLAUDE"
    return node_ids.get(text_field(agent), "A_CLAUDE")


def review_label(record: dict[str, object], *, typed: bool, evidence_id: str) -> str:
    kind = text_field(record.get("kind")) or "review"
    result = text_field(record.get("result")) or "unknown"
    label = f"{evidence_id} · {kind} review: {result}" if evidence_id else f"{kind} review: {result}"
    reviewer = text_field(record.get("reviewer"))
    second_line = ""
    if reviewer:
        second_line = reviewer
    elif not evidence_task_refs(record, include_covers_tasks=not typed):
        second_line = "run-wide"
    return mermaid_node_label([label, second_line])


def verification_label(record: dict[str, object], *, evidence_id: str) -> str:
    kind = text_field(record.get("kind")) or "verification"
    result = text_field(record.get("result")) or "unknown"
    prefix = f"{evidence_id} · " if evidence_id else ""
    return mermaid_label(f"{prefix}{kind}: {result}")


def task_node_label(task: dict[str, object]) -> str:
    task_id = text_field(task.get("id")) or "unknown"
    title = mermaid_label(graph_task_label(task, task_id), limit=32)
    status = text_field(task.get("status")) or "unknown"
    return mermaid_label(f"{task_id}: {title} ({status})", limit=120)


def first_blocking_reason(record: dict[str, object]) -> str:
    blocking = string_list(record.get("blocking"))
    if blocking:
        return blocking[0]
    return "gate failed"


def evidence_record_ids(ledger: list[dict[str, object]]) -> dict[int, str]:
    ids: dict[int, str] = {}
    verification_count = 0
    review_count = 0
    for record in ledger:
        record_type = record.get("type")
        if record_type == "verification":
            if record.get("kind") in REVIEW_KINDS:
                review_count += 1
                ids[id(record)] = f"R{review_count}"
            else:
                verification_count += 1
                ids[id(record)] = f"V{verification_count}"
        elif record_type == "review":
            review_count += 1
            ids[id(record)] = f"R{review_count}"
    return ids


def graph_record_nodes(
    ledger: list[dict[str, object]],
) -> tuple[
    list[dict[str, object]],
    list[dict[str, object]],
    list[dict[str, object]],
    dict[str, str],
]:
    record_ids = evidence_record_ids(ledger)
    verification_nodes: list[dict[str, object]] = []
    review_nodes: list[dict[str, object]] = []
    consensus_nodes: list[dict[str, object]] = []
    verification_ref_nodes: dict[str, str] = {}
    consensus_count = 0

    for record in ledger:
        record_type = record.get("type")
        if record_type == "verification":
            node_id = record_ids.get(id(record))
            if not node_id:
                continue
            if record.get("kind") in REVIEW_KINDS:
                review_nodes.append({"id": node_id, "record": record, "typed": False})
            else:
                verification_nodes.append({"id": node_id, "record": record})
            verification_id = text_field(record.get("id"))
            if verification_id:
                verification_ref_nodes[verification_id] = node_id
        elif record_type == "review":
            node_id = record_ids.get(id(record))
            if node_id:
                review_nodes.append({"id": node_id, "record": record, "typed": True})
        elif record_type == "consensus":
            consensus_count += 1
            consensus_nodes.append({"id": f"C{consensus_count}", "record": record})

    return verification_nodes, review_nodes, consensus_nodes, verification_ref_nodes


def task_owner_by_id(tasks: list[dict[str, object]]) -> dict[str, str]:
    owners: dict[str, str] = {}
    for task in tasks:
        task_id = text_field(task.get("id"))
        owner = text_field(task.get("owner"))
        if task_id and owner:
            owners[task_id] = owner
    return owners


def add_review_edges(
    node: dict[str, object],
    node_ids: dict[str, str],
    task_owners: dict[str, str],
    add_edge: object,
) -> None:
    record = node["record"]
    if not isinstance(record, dict):
        return
    reviewer = text_field(record.get("reviewer"))
    result = text_field(record.get("result")) or "unknown"
    kind = text_field(record.get("kind")) or "review"
    target = str(node["id"])
    if not reviewer or is_hub_agent(reviewer):
        add_edge("A_CLAUDE", "-->", "review", target, f"review {kind} {result}")
    else:
        reviewer_id = agent_node_id(reviewer, node_ids)
        add_edge("A_CLAUDE", "-->", "request review", reviewer_id)
        add_edge(reviewer_id, "-->", "review", target, f"review {kind} {result}")
    task_id = text_field(record.get("task_id"))
    owner = task_owners.get(task_id)
    if result == "failed" and owner:
        add_edge(target, "-->", "blocked: fix required", agent_node_id(owner, node_ids))


def evidence_task_refs(record: dict[str, object], *, include_covers_tasks: bool) -> list[str]:
    refs: list[str] = []
    task_id = text_field(record.get("task_id"))
    if task_id:
        refs.append(task_id)
    if include_covers_tasks:
        refs.extend(string_list(record.get("covers_tasks")))
    deduped: list[str] = []
    seen: set[str] = set()
    for ref in refs:
        if ref in seen:
            continue
        seen.add(ref)
        deduped.append(ref)
    return deduped


def class_suffix(class_name: str) -> str:
    return f":::{class_name}" if class_name else ""


def task_status_class(status: object) -> str:
    status_text = text_field(status)
    if status_text == "complete":
        return "ok"
    if status_text in {"failed", "blocked"}:
        return "bad"
    return ""


def evidence_result_class(result: object) -> str:
    result_text = text_field(result)
    if result_text == "passed":
        return "ok"
    if result_text == "failed":
        return "bad"
    if result_text in {"skipped", "inconclusive", "needs_human_review"}:
        return "attention"
    return ""


def consensus_outcome_class(outcome: object) -> str:
    outcome_text = text_field(outcome)
    if outcome_text in {"consensus", "rerun_passed"}:
        return "ok"
    if outcome_text == "rejected":
        return "bad"
    return "attention"


def render_orchestration_graph(
    lines: list[str],
    state: dict[str, object],
    ledger: list[dict[str, object]],
) -> None:
    lines.extend(["## Orchestration Graph", ""])
    tasks = task_graph_records(ledger)
    agent_order, agent_info = collect_agent_info(state, ledger, tasks)
    verification_nodes, review_nodes, consensus_nodes, verification_ref_nodes = graph_record_nodes(ledger)
    gate_record = latest_record(ledger, "gate_result")
    protocol_events = any(
        record.get("type")
        in {
            "dispatch_started",
            "dispatch_completed",
            "task_checkpoint",
            "review",
            "verification",
            "consensus",
            "gate_result",
        }
        for record in ledger
    )
    if not tasks and not agent_order and not protocol_events:
        lines.extend([ORCHESTRATION_GRAPH_PLACEHOLDER, ""])
        return

    node_ids = agent_node_ids(agent_order)
    task_nodes = {text_field(task.get("id")): task_node_id(text_field(task.get("id"))) for task in tasks}
    task_owners = task_owner_by_id(tasks)
    latest_checkpoint_by_task: dict[str, dict[str, object]] = {}
    latest_dispatch_completed_by_task: dict[str, dict[str, object]] = {}

    for record in ledger:
        task_id = text_field(record.get("task_id"))
        if record.get("type") == "task_checkpoint" and task_id:
            latest_checkpoint_by_task[task_id] = record
        elif record.get("type") == "dispatch_completed" and task_id:
            latest_dispatch_completed_by_task[task_id] = record

    edge_lines: list[str] = []
    fallback_edges: list[str] = []
    seen_edges: set[tuple[str, str, str, str]] = set()

    def add_edge(source: str, arrow: str, label: str, target: str, fallback: str = "") -> None:
        safe_label = mermaid_label(label)
        key = (source, arrow, safe_label, target)
        if key in seen_edges:
            return
        seen_edges.add(key)
        label_part = f'|"{safe_label}"|' if safe_label else ""
        edge_lines.append(f"  {source} {arrow}{label_part} {target}")
        if fallback:
            fallback_edges.append(fallback)

    def add_subject_edges(source: str, refs: list[str], label: str) -> None:
        for ref in refs:
            target = task_nodes.get(ref)
            if target:
                add_edge(source, "-.->", label, target)

    evidence_node_ids = [node["id"] for node in verification_nodes + review_nodes + consensus_nodes]
    used_classes: set[str] = set()

    def node_class(class_name: str) -> str:
        if class_name:
            used_classes.add(class_name)
        return class_suffix(class_name)

    lines.extend(["```mermaid", "flowchart TD"])
    lines.append(f'  A_CLAUDE{{{{"{mermaid_node_label(["Claude Code", "planner · orchestrator"])}"}}}}')
    for agent in agent_order:
        info = agent_info[agent]
        label_parts = [agent]
        model = text_field(info.get("model"))
        reasoning_effort = text_field(info.get("reasoning_effort"))
        if model or reasoning_effort:
            label_parts.append(f"{model or 'unknown'} · {reasoning_effort or 'unknown'}")
        mode = text_field(info.get("mode"))
        status = text_field(info.get("status"))
        if mode or status:
            label_parts.append(f"{mode or 'unknown'} · {status or 'unknown'}")
        else:
            label_parts.append("unknown")
        lines.append(f'  {node_ids[agent]}[["{mermaid_node_label(label_parts)}"]]')
    for task in tasks:
        task_id = text_field(task.get("id"))
        if not task_id:
            continue
        status_class = node_class(task_status_class(task.get("status")))
        lines.append(f'  {task_nodes[task_id]}["{task_node_label(task)}"]{status_class}')
    for node in verification_nodes:
        record = node["record"]
        result_class = node_class(evidence_result_class(record.get("result")))
        lines.append(
            f'  {node["id"]}[/"{verification_label(record, evidence_id=str(node["id"]))}"/]{result_class}'
        )
    for node in review_nodes:
        record = node["record"]
        result_class = node_class(evidence_result_class(record.get("result")))
        lines.append(
            f'  {node["id"]}[/"{review_label(record, typed=bool(node["typed"]), evidence_id=str(node["id"]))}"/]{result_class}'
        )
    for node in consensus_nodes:
        outcome = graph_consensus_outcome(node["record"])
        outcome_class = node_class(consensus_outcome_class(outcome))
        lines.append(f'  {node["id"]}{{"consensus: {mermaid_label(outcome)}"}}{outcome_class}')
    if gate_record:
        ok = gate_result_ok(gate_record) is True
        gate_class = node_class("ok" if ok else "bad")
        lines.append(f'  G{{"gate: {"ok" if ok else "blocked"}"}}{gate_class}')
        if ok:
            lines.append(f'  DONE((("run accepted"))){node_class("ok")}')

    for task in tasks:
        task_id = text_field(task.get("id"))
        target = task_nodes.get(task_id)
        if target:
            add_edge("A_CLAUDE", "-->", "task_created", target)
    verification_node_by_record = {id(node["record"]): node for node in verification_nodes}
    review_node_by_record = {id(node["record"]): node for node in review_nodes}
    consensus_node_by_record = {id(node["record"]): node for node in consensus_nodes}
    seen_dispatch_tasks: set[str] = set()

    for record in ledger:
        record_type = record.get("type")
        task_id = text_field(record.get("task_id"))
        if record_type == "dispatch_started":
            if not task_id or task_id in seen_dispatch_tasks:
                continue
            seen_dispatch_tasks.add(task_id)
            agent = text_field(record.get("agent"))
            target = agent_node_id(agent, node_ids)
            freshness = "fresh" if record.get("fresh_session") is not False else "reuse"
            add_edge(
                "A_CLAUDE",
                "-->",
                f"dispatch_started: {task_id} ({freshness})",
                target,
                f"dispatch {task_id} ({freshness})",
            )
        elif record_type == "task_checkpoint":
            if not task_id or latest_checkpoint_by_task.get(task_id) is not record:
                continue
            target = task_nodes.get(task_id)
            if not target:
                continue
            source = agent_node_id(record.get("agent"), node_ids)
            status = text_field(record.get("status")) or "unknown"
            add_edge(source, "==>", f"task_checkpoint: {status}", target)
        elif record_type == "dispatch_completed":
            if (
                not task_id
                or task_id in latest_checkpoint_by_task
                or latest_dispatch_completed_by_task.get(task_id) is not record
            ):
                continue
            target = task_nodes.get(task_id)
            if not target:
                continue
            source = agent_node_id(record.get("agent"), node_ids)
            status = text_field(record.get("status")) or "unknown"
            add_edge(source, "==>", f"dispatch_completed: {status}", target)
        elif record_type == "verification":
            verification_node = verification_node_by_record.get(id(record))
            if verification_node:
                kind = text_field(record.get("kind")) or "verification"
                result = text_field(record.get("result")) or "unknown"
                add_edge(
                    "A_CLAUDE",
                    "==>",
                    "add_verification",
                    str(verification_node["id"]),
                    f"verification {kind} {result}",
                )
                add_subject_edges(
                    str(verification_node["id"]),
                    evidence_task_refs(record, include_covers_tasks=True),
                    "covers",
                )
                continue
            review_node = review_node_by_record.get(id(record))
            if review_node:
                add_review_edges(review_node, node_ids, task_owners, add_edge)
                add_subject_edges(
                    str(review_node["id"]),
                    evidence_task_refs(record, include_covers_tasks=True),
                    "reviews",
                )
        elif record_type == "review":
            review_node = review_node_by_record.get(id(record))
            if review_node:
                add_review_edges(review_node, node_ids, task_owners, add_edge)
                add_subject_edges(
                    str(review_node["id"]),
                    evidence_task_refs(record, include_covers_tasks=False),
                    "reviews",
                )
        elif record_type == "consensus":
            node = consensus_node_by_record.get(id(record))
            if not node:
                continue
            target = str(node["id"])
            add_edge(
                "A_CLAUDE",
                "-->",
                "consensus",
                target,
                f"consensus {graph_consensus_outcome(record)}",
            )
            for ref in [*string_list(record.get("clears")), *string_list(record.get("evidence_refs"))]:
                parsed = parse_ref(ref)
                if parsed is None:
                    continue
                ref_type, ref_id = parsed
                if ref_type != "verification":
                    continue
                source = verification_ref_nodes.get(ref_id)
                if source:
                    add_edge(source, "-.->", "clears", target)
    if gate_record:
        for source in evidence_node_ids:
            add_edge(str(source), "-->", "", "G")
        ok = gate_result_ok(gate_record) is True
        if ok:
            add_edge("G", "-->", "ok", "DONE", "gate ok")
        else:
            reason = first_blocking_reason(gate_record)
            add_edge("G", "-->", f"blocked: {reason}", "A_CLAUDE", f"gate blocked: {reason}")

    lines.extend(edge_lines)
    class_defs = {
        "ok": "classDef ok fill:#dcefdc,stroke:#0ca30c,color:#10320f",
        "attention": "classDef attention fill:#fdeecd,stroke:#b97b00,color:#3d2b00",
        "bad": "classDef bad fill:#f8d7d7,stroke:#d03b3b,color:#3f0f0f",
    }
    for class_name in ("ok", "attention", "bad"):
        if class_name in used_classes:
            lines.append(f"  {class_defs[class_name]}")
    lines.extend(["```", ""])
    lines.append("Flow: " + (" · ".join(fallback_edges) if fallback_edges else "no protocol edges recorded"))
    lines.append("")

    for task in tasks:
        task_id = text_field(task.get("id")) or "unknown"
        title = text_field(task.get("title")) or task_id
        status = text_field(task.get("status")) or "unknown"
        lines.append(f"- **{task_id}**: {title} ({status})")
        lines.append(f"  - Owner: {text_field(task.get('owner')) or 'not recorded'}")
        lines.append(
            f"  - Files allowed: {brief_string_list(task.get('files_allowed'), code=True) or 'not recorded'}"
        )
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
