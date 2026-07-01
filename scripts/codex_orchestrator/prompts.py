from __future__ import annotations

from pathlib import Path

from .gate import text_value
from .store import plugin_root


PROMPT_TEMPLATE_FILES = {
    "impl": "task-prompt.md",
    "review": "review-prompt.md",
}


def markdown_list(value: object) -> str:
    if isinstance(value, str) and value:
        return f"- {value}"
    if isinstance(value, list):
        items = [item for item in value if isinstance(item, str) and item]
        if items:
            return "\n".join(f"- {item}" for item in items)
    return "none"


def prompt_template_path(kind: str) -> Path:
    return plugin_root() / "templates" / PROMPT_TEMPLATE_FILES[kind]


def task_created_record(records: list[dict[str, object]], task_id: str) -> dict[str, object]:
    matches = [
        record
        for record in records
        if record.get("type") == "task_created" and record.get("id") == task_id
    ]
    if not matches:
        raise SystemExit(f"ERROR: no task_created record found for task id {task_id}")
    return matches[-1]


def prompt_context(record: dict[str, object]) -> dict[str, str]:
    title = text_value(record.get("title")) or ""
    goal = text_value(record.get("goal")) or text_value(record.get("summary")) or title
    return {
        "task_id": text_value(record.get("id")) or "",
        "title": title,
        "files_allowed": markdown_list(record.get("files_allowed")),
        "files_forbidden": markdown_list(record.get("files_forbidden")),
        "acceptance": markdown_list(record.get("acceptance")),
        "verification_required": markdown_list(record.get("verification_required")),
        "context": markdown_list(record.get("context")),
        "constraints": markdown_list(record.get("constraints")),
        "goal": goal,
    }


def render_prompt_template(template: str, context: dict[str, str]) -> str:
    rendered = template
    for key, value in context.items():
        rendered = rendered.replace(f"{{{{ {key} }}}}", value)
        rendered = rendered.replace(f"{{{{{key}}}}}", value)
    return rendered
