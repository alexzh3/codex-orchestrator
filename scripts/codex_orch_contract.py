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
CONSENSUS_OUTCOME_ORDER = ("consensus", "claude_decision", "user_action_required")
ALLOWED_RISK_LEVELS = ("none", "low", "medium", "high")

LEGACY_CONSENSUS_STATUS_OUTCOMES = {
    "accepted": "consensus",
    "resolved": "consensus",
    "deferred": "user_action_required",
    "rejected": "user_action_required",
}
ALLOWED_LEGACY_CONSENSUS_STATUSES = set(LEGACY_CONSENSUS_STATUS_OUTCOMES)
