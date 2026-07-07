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


def review_label(record: dict[str, object], *, typed: bool, evidence_id: str) -> str:
    kind = text_field(record.get("kind")) or "review"
    result = text_field(record.get("result")) or "unknown"
    label = f"{evidence_id} · {kind} review: {result}"
    if not evidence_task_refs(record, include_covers_tasks=not typed):
        label += " · run-wide"
    return mermaid_label(label)


def verification_label(record: dict[str, object], *, evidence_id: str) -> str:
    kind = text_field(record.get("kind")) or "verification"
    result = text_field(record.get("result")) or "unknown"
    return mermaid_label(f"{evidence_id} · {kind}: {result}")


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


def role_label(roles: set[str]) -> str:
    if "implementer" in roles and "reviewer" in roles:
        return "implementer · reviewer"
    if "reviewer" in roles:
        return "peer reviewer"
    if "implementer" in roles:
        return "implementer"
    return ""


def build_session_trace(
    state: dict[str, object],
    ledger: list[dict[str, object]],
) -> dict[str, object]:
    sessions = state.get("sessions") if isinstance(state.get("sessions"), list) else []
    session_order: list[dict[str, object]] = []
    sessions_by_agent: dict[str, list[dict[str, object]]] = {}
    current_by_agent: dict[str, dict[str, object]] = {}
    state_by_agent: dict[str, dict[str, object]] = {}
    roles_by_agent: dict[str, set[str]] = {}
    agent_base_ids: dict[str, str] = {}
    used_node_ids: set[str] = {"A_CLAUDE"}
    agent_seen_dispatch: set[str] = set()
    session_task_status: dict[tuple[str, str], dict[str, str]] = {}
    task_delivery_session: dict[str, str] = {}
    review_session_by_record: dict[int, str] = {}

    def unique_node_id(base: str) -> str:
        node_id = base
        suffix = 2
        while node_id in used_node_ids:
            node_id = f"{base}_{suffix}"
            suffix += 1
        used_node_ids.add(node_id)
        return node_id

    def base_for_agent(agent: str) -> str:
        if agent not in agent_base_ids:
            agent_base_ids[agent] = unique_node_id(f"A_{graph_slug(agent)}")
        return agent_base_ids[agent]

    def ensure_roles(agent: str) -> set[str]:
        return roles_by_agent.setdefault(agent, set())

    def create_session(agent: str) -> dict[str, object]:
        number = len(sessions_by_agent.get(agent, [])) + 1
        base = base_for_agent(agent)
        node_id = base if number == 1 else unique_node_id(f"{base}_S{number}")
        session = {
            "agent": agent,
            "number": number,
            "node_id": node_id,
            "dispatches": [],
            "model": "",
            "reasoning_effort": "",
            "mode": "",
            "status": "",
        }
        sessions_by_agent.setdefault(agent, []).append(session)
        current_by_agent[agent] = session
        session_order.append(session)
        ensure_roles(agent)
        return session

    def ensure_session(agent: object) -> dict[str, object] | None:
        agent_name = text_field(agent)
        if not agent_name or is_hub_agent(agent_name):
            return None
        return current_by_agent.get(agent_name) or create_session(agent_name)

    def set_session_field(session: dict[str, object], field: str, value: object) -> None:
        text = text_field(value)
        if text and not text_field(session.get(field)):
            session[field] = text

    def task_status_slot(session: dict[str, object], task_id: str) -> dict[str, str]:
        key = (str(session["node_id"]), task_id)
        task_delivery_session[task_id] = str(session["node_id"])
        return session_task_status.setdefault(key, {"dispatch_completed": "", "task_checkpoint": ""})

    for session in sessions:
        if not isinstance(session, dict):
            continue
        agent = text_field(session.get("name"))
        if not agent or is_hub_agent(agent):
            continue
        state_by_agent[agent] = session
        ensure_session(agent)

    for record in ledger:
        record_type = record.get("type")
        if record_type == "dispatch_started":
            agent = text_field(record.get("agent"))
            if not agent or is_hub_agent(agent):
                continue
            if agent in agent_seen_dispatch and record.get("fresh_session") is True:
                session = create_session(agent)
            else:
                session = ensure_session(agent)
            if not session:
                continue
            agent_seen_dispatch.add(agent)
            ensure_roles(agent).add("implementer")
            session["dispatches"].append(record)
            set_session_field(session, "model", record.get("model"))
            set_session_field(session, "reasoning_effort", record.get("reasoning_effort"))
            set_session_field(session, "mode", record.get("mode"))
            task_id = text_field(record.get("task_id"))
            if task_id:
                task_status_slot(session, task_id)
        elif record_type in {"dispatch_completed", "task_checkpoint"}:
            session = ensure_session(record.get("agent"))
            if not session:
                continue
            ensure_roles(text_field(session.get("agent"))).add("implementer")
            task_id = text_field(record.get("task_id"))
            status = text_field(record.get("status"))
            if task_id:
                task_status_slot(session, task_id)[record_type] = status
            if status:
                session["status"] = status
        elif record_type == "review":
            reviewer = text_field(record.get("reviewer"))
            if reviewer and not is_hub_agent(reviewer):
                session = ensure_session(reviewer)
                if session:
                    ensure_roles(reviewer).add("reviewer")
                    review_session_by_record[id(record)] = str(session["node_id"])
        elif record_type == "verification" and record.get("kind") in REVIEW_KINDS:
            reviewer = text_field(record.get("reviewer"))
            if reviewer and not is_hub_agent(reviewer):
                session = ensure_session(reviewer)
                if session:
                    ensure_roles(reviewer).add("reviewer")
                    review_session_by_record[id(record)] = str(session["node_id"])

    for agent, state_session in state_by_agent.items():
        latest = current_by_agent.get(agent)
        if not latest:
            continue
        set_session_field(latest, "mode", state_session.get("mode"))
        state_status = text_field(state_session.get("status"))
        if state_status:
            latest["status"] = state_status

    return {
        "sessions": session_order,
        "roles_by_agent": roles_by_agent,
        "session_task_status": session_task_status,
        "task_delivery_session": task_delivery_session,
        "review_session_by_record": review_session_by_record,
    }


def render_orchestration_graph(
    lines: list[str],
    state: dict[str, object],
    ledger: list[dict[str, object]],
) -> None:
    lines.extend(["## Orchestration Graph", ""])
    tasks = task_graph_records(ledger)
    session_trace = build_session_trace(state, ledger)
    session_nodes = session_trace["sessions"]
    roles_by_agent = session_trace["roles_by_agent"]
    session_task_status = session_trace["session_task_status"]
    task_delivery_session = session_trace["task_delivery_session"]
    review_session_by_record = session_trace["review_session_by_record"]
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
    if not tasks and not session_nodes and not protocol_events:
        lines.extend([ORCHESTRATION_GRAPH_PLACEHOLDER, ""])
        return

    task_nodes = {text_field(task.get("id")): task_node_id(text_field(task.get("id"))) for task in tasks}

    edge_lines: list[str] = []
    fallback_edges: list[str] = []
    seen_fallback_edges: set[str] = set()
    seen_edges: set[tuple[str, str, str, str]] = set()

    def add_fallback(text: str) -> None:
        if text and text not in seen_fallback_edges:
            seen_fallback_edges.add(text)
            fallback_edges.append(text)

    def add_edge(source: str, arrow: str, label: str, target: str, fallback: str = "") -> None:
        safe_label = mermaid_label(label)
        key = (source, arrow, safe_label, target)
        if key in seen_edges:
            return
        seen_edges.add(key)
        label_part = f'|"{safe_label}"|' if safe_label else ""
        edge_lines.append(f"  {source} {arrow}{label_part} {target}")
        if fallback:
            add_fallback(fallback)

    evidence_node_ids = [node["id"] for node in verification_nodes + review_nodes + consensus_nodes]
    used_classes: set[str] = set()

    def node_class(class_name: str) -> str:
        if class_name:
            used_classes.add(class_name)
        return class_suffix(class_name)

    lines.extend(["```mermaid", "flowchart TD"])
    lines.append(f'  A_CLAUDE{{{{"{mermaid_node_label(["Claude Code", "planner · orchestrator"])}"}}}}')
    for session in session_nodes:
        if not isinstance(session, dict):
            continue
        agent = text_field(session.get("agent"))
        role = role_label(roles_by_agent.get(agent, set()))
        label_parts = [f"{agent} · {role}" if role else agent]
        number = int(session.get("number") or 1)
        session_line = f"session {number}"
        if number >= 2:
            session_line += " (fresh restart)"
        model = text_field(session.get("model"))
        reasoning_effort = text_field(session.get("reasoning_effort"))
        if model or reasoning_effort:
            session_line += f" · {model or 'unknown'} · {reasoning_effort or 'unknown'}"
        label_parts.append(session_line)
        mode = text_field(session.get("mode"))
        status = text_field(session.get("status"))
        if mode or status:
            label_parts.append(f"{mode or 'unknown'} · {status or 'unknown'}")
        else:
            label_parts.append("unknown")
        lines.append(f'  {session["node_id"]}[["{mermaid_node_label(label_parts)}"]]')
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

    verification_node_by_record = {id(node["record"]): node for node in verification_nodes}
    review_node_by_record = {id(node["record"]): node for node in review_nodes}
    consensus_node_by_record = {id(node["record"]): node for node in consensus_nodes}
    delivered_tasks = {task_id for _, task_id in session_task_status}

    for task in tasks:
        task_id = text_field(task.get("id"))
        target = task_nodes.get(task_id)
        if target and task_id not in delivered_tasks:
            add_edge("A_CLAUDE", "-->", "task_created", target)

    for session in session_nodes:
        if not isinstance(session, dict):
            continue
        session_id = str(session.get("node_id"))
        dispatches = session.get("dispatches")
        if isinstance(dispatches, list) and dispatches:
            label = f"dispatch ×{len(dispatches)}"
            if len(dispatches) == 1:
                task_id = text_field(dispatches[0].get("task_id"))
                if task_id:
                    label += f": {task_id}"
            add_edge(
                "A_CLAUDE",
                "-->",
                label,
                session_id,
                label,
            )
        for (node_id, task_id), statuses in session_task_status.items():
            if node_id != session_id:
                continue
            target = task_nodes.get(task_id)
            if not target:
                continue
            status = statuses.get("dispatch_completed") or statuses.get("task_checkpoint") or "unknown"
            add_edge(session_id, "==>", status, target)

    def chain_evidence_to_tasks(
        record: dict[str, object], node_id: str, *, include_covers_tasks: bool, descriptor: str
    ) -> None:
        refs = evidence_task_refs(record, include_covers_tasks=include_covers_tasks)
        for ref in refs:
            target = task_nodes.get(ref)
            if target:
                add_edge(target, "-->", "", node_id)
        add_fallback(f"{refs[0]} → {descriptor}" if refs else f"run-wide {descriptor}")

    def add_review_chain(record: dict[str, object], node_id: str, *, include_covers_tasks: bool) -> None:
        produced_by = review_session_by_record.get(id(record))
        if produced_by:
            add_edge(produced_by, "-->", "produced", node_id)
        kind = text_field(record.get("kind")) or "review"
        result = text_field(record.get("result")) or "unknown"
        chain_evidence_to_tasks(
            record, node_id, include_covers_tasks=include_covers_tasks, descriptor=f"{kind} review {result}"
        )
        task_id = text_field(record.get("task_id"))
        if result == "failed" and task_id in task_delivery_session:
            add_edge(node_id, "-->", "blocked: fix required", str(task_delivery_session[task_id]))

    for record in ledger:
        record_type = record.get("type")
        if record_type == "verification":
            verification_node = verification_node_by_record.get(id(record))
            if verification_node:
                kind = text_field(record.get("kind")) or "verification"
                result = text_field(record.get("result")) or "unknown"
                chain_evidence_to_tasks(
                    record,
                    str(verification_node["id"]),
                    include_covers_tasks=True,
                    descriptor=f"{kind} {result}",
                )
                continue
            review_node = review_node_by_record.get(id(record))
            if review_node:
                add_review_chain(record, str(review_node["id"]), include_covers_tasks=True)
        elif record_type == "review":
            review_node = review_node_by_record.get(id(record))
            if review_node:
                add_review_chain(record, str(review_node["id"]), include_covers_tasks=False)
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
