# Codex Exec Reference

Use this when starting, resuming, or asking Codex to review through the CLI.

## Locate Codex

There may be no `codex` on `PATH`; IDE extensions ship their own binary and version directories
change. Locate it rather than hardcoding:

```bash
CODEX=$(
  find ~/.cursor/extensions ~/.vscode/extensions ~/.vscode-server/extensions \
    -maxdepth 4 -name codex -type f 2>/dev/null | head -1
)
```

## Start Or Resume

```bash
"$CODEX" exec [OPTIONS] "<prompt>"
"$CODEX" exec resume <thread-uuid> "<prompt>"
"$CODEX" exec resume --last "<prompt>"
```

`resume` replays the thread context, then runs your prompt as the next turn. Resume only when the
session is idle or complete; do not race a live turn. Each resume may append a new rollout, so re-run
rollout discovery afterwards.

For long prompts, pass stdin to avoid shell escaping:

```bash
cat prompt.md | "$CODEX" exec -s workspace-write -c approval_policy=never
```

Always preserve history. Do not use `--ephemeral`; it breaks resumability and audit logs.

## Visibility

If the user wants the session visible in the Codex IDE sidebar, ask them to start Codex in the IDE
and paste the `codex://threads/<thread-uuid>` URL. Headless `codex exec` sessions are source kind
`exec`; they are CLI-resumable with `codex resume --all --include-non-interactive` but do not appear
in the IDE sidebar.

## Run Modes

Headless `codex exec` has no user present to approve IDE escalation prompts, so choose the mode up
front.

Default executor mode for code work:

```bash
"$CODEX" exec -s workspace-write -c approval_policy=never "<prompt>"
```

This lets Codex edit the workspace and never pause for approval. Docker, GPU, network, and
out-of-workspace writes remain blocked; Claude should run or gate those steps.

Autonomous mode is only for sessions where the user explicitly authorizes broad access:

```bash
"$CODEX" exec --dangerously-bypass-approvals-and-sandbox "<prompt>"
```

Use this only with explicit durable authorization. Prefer executor mode plus Claude-side gating for
normal orchestration.

Useful flags: `-m <model>`, `-c model_reasoning_effort="xhigh"`, `-c service_tier="priority"`,
`-C/--cd <dir>`, `--add-dir <dir>`, `--skip-git-repo-check`, `-o/--output-last-message <file>`,
`--json`, and `-i/--image`.

## Peer Review

Ask Codex to review code with:

```bash
"$CODEX" exec review --uncommitted
"$CODEX" exec review --base <branch>
"$CODEX" exec review --commit <sha>
```

Use `--uncommitted` before commit to have Codex critique the current working-tree diff.

## Unsupported Visibility Workaround

Spoofing rollout metadata with `source: vscode` for IDE visibility is experimental and unsupported.
Prefer starting in the IDE and passing Claude the thread URL.
