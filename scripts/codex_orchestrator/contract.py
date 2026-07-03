from __future__ import annotations


ALLOWED_VERIFICATION_KINDS = (
    "git_diff",
    "test",
    "typecheck",
    "lint",
    "build",
    "benchmark",
    "screenshot",
    "artifact_check",
    "manual_review",
    "custom",
)

ALLOWED_VERIFICATION_RESULTS = (
    "passed",
    "failed",
    "skipped",
    "inconclusive",
    "needs_human_review",
)

TASK_STATUS_ORDER = ("complete", "active", "pending", "blocked", "failed")
SESSION_STATUS_ORDER = ("active", "idle", "complete", "failed", "awaiting-approval", "unknown")
STATE_STATUS_ORDER = ("active", "blocked", "complete", "needs_review", "accepted", "rejected")
DISPATCH_MODE_ORDER = ("ide", "exec")
REVIEW_KIND_ORDER = ("diff", "test", "manual", "custom")
VERIFICATION_SCOPE_ORDER = ("task", "global")
CONSENSUS_OUTCOME_ORDER = ("consensus", "claude_decision", "user_action_required")
RESOLUTION_BASIS_ORDER = (
    "rerun_passed",
    "repro_not_reproduced",
    "accepted_risk",
    "non_executable_convention",
    "user_override",
)
DEFAULT_RESOLUTION_BASIS = "non_executable_convention"
FINDING_SEVERITY_ORDER = ("P0", "P1", "P2")
DEFAULT_FINDING_SEVERITY = "P1"
ALLOWED_RISK_LEVELS = ("none", "low", "medium", "high")

LEGACY_CONSENSUS_STATUS_OUTCOMES = {
    "accepted": "consensus",
    "resolved": "consensus",
    "deferred": "user_action_required",
    "rejected": "user_action_required",
}
ALLOWED_LEGACY_CONSENSUS_STATUSES = set(LEGACY_CONSENSUS_STATUS_OUTCOMES)

RUN_META_CONFIG_FIELDS = (
    "session_reuse_policy",
    "require_final_codex_review",
    "require_file_claims",
)
RUN_META_CONFIG_BOOLEAN_FIELDS = (
    "require_final_codex_review",
    "require_file_claims",
)
