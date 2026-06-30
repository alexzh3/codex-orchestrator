# Codex Implementation Task: {{ task_id }} - {{ title }}

You are the implementation agent for task `{{ task_id }}`.

## Goal

{{ goal }}

## Context

{{ context }}

## Constraints

{{ constraints }}

## Files Allowed

{{ files_allowed }}

## Files Forbidden

{{ files_forbidden }}

## Acceptance

{{ acceptance }}

## Verification Required

{{ verification_required }}

## Output Contract

Return only a JSON object matching `schemas/codex-task-output.schema.json`:

```json
{
  "summary": "string",
  "files_changed": ["string"],
  "tests_run": [
    {"command": "string", "exit_code": 0, "result": "string"}
  ],
  "unresolved_blockers": ["string"]
}
```
