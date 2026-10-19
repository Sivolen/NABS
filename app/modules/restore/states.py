"""
State machine of a restore job. Pure code: the table of allowed transitions.

The persistent change of a state must be done by the service as ONE atomic
"UPDATE ... WHERE status = :expected" (see transition_allowed_from()), so that a
repeated HTTP request, a second worker or a restart can never start a job twice.
"""

from typing import Dict, FrozenSet

CREATED = "created"
PRECHECK_RUNNING = "precheck_running"
AWAITING_CONFIRMATION = "awaiting_confirmation"
QUEUED = "queued"
RUNNING = "running"
VERIFYING = "verifying"
ROLLBACK_RUNNING = "rollback_running"
SUCCESS = "success"
FAILED = "failed"
FAILED_ROLLBACK_CONFIRMED = "failed_rollback_confirmed"
ROLLBACK_FAILED = "rollback_failed"
UNKNOWN = "unknown"
RESOLVED_MANUAL = "resolved_manual"
CANCELLED = "cancelled"

TRANSITIONS: Dict[str, FrozenSet[str]] = {
    CREATED: frozenset({PRECHECK_RUNNING, CANCELLED}),
    # blocked prechecks end as FAILED: nothing was changed on the device
    PRECHECK_RUNNING: frozenset({AWAITING_CONFIRMATION, FAILED, CANCELLED}),
    # conditions changed after the precheck -> run it again and ask again
    AWAITING_CONFIRMATION: frozenset({QUEUED, PRECHECK_RUNNING, CANCELLED}),
    # UNKNOWN: the worker/application died while the job was queued or claimed
    QUEUED: frozenset({RUNNING, CANCELLED, UNKNOWN}),
    RUNNING: frozenset({VERIFYING, ROLLBACK_RUNNING, FAILED, UNKNOWN}),
    VERIFYING: frozenset({SUCCESS, ROLLBACK_RUNNING, FAILED, UNKNOWN}),
    ROLLBACK_RUNNING: frozenset({FAILED_ROLLBACK_CONFIRMED, ROLLBACK_FAILED, UNKNOWN}),
    SUCCESS: frozenset(),
    FAILED: frozenset(),
    FAILED_ROLLBACK_CONFIRMED: frozenset(),
    ROLLBACK_FAILED: frozenset({RESOLVED_MANUAL}),
    UNKNOWN: frozenset({RESOLVED_MANUAL}),
    RESOLVED_MANUAL: frozenset(),
    CANCELLED: frozenset(),
}

ALL_STATES = frozenset(TRANSITIONS)
# Terminal for worker execution. `unknown` and `rollback_failed` may only be closed by an
# explicit, audited human resolution; they must not be re-queued or auto-retried.
TERMINAL_STATES = frozenset(
    {
        SUCCESS,
        FAILED,
        FAILED_ROLLBACK_CONFIRMED,
        ROLLBACK_FAILED,
        UNKNOWN,
        RESOLVED_MANUAL,
        CANCELLED,
    }
)
# the device may already have been changed: cancelling is no longer possible
DEVICE_TOUCHED_STATES = frozenset({RUNNING, VERIFYING, ROLLBACK_RUNNING})
# claimed by a worker that died: never resumed automatically, they go to UNKNOWN.
# A job still QUEUED was never started, so a restart leaves it queued (it expires by
# its confirmation age instead).
INTERRUPTED_ON_RESTART = DEVICE_TOUCHED_STATES
CANCELLABLE_STATES = frozenset(s for s in ALL_STATES if CANCELLED in TRANSITIONS[s])

LABELS: Dict[str, str] = {
    CREATED: "Created",
    PRECHECK_RUNNING: "Running prechecks",
    AWAITING_CONFIRMATION: "Awaiting confirmation",
    QUEUED: "Queued",
    RUNNING: "Restoring",
    VERIFYING: "Verifying result",
    ROLLBACK_RUNNING: "Rolling back",
    SUCCESS: "Restored and verified",
    FAILED: "Failed",
    FAILED_ROLLBACK_CONFIRMED: "Failed, rollback confirmed",
    ROLLBACK_FAILED: "Rollback failed - device needs attention",
    UNKNOWN: "Result unknown - manual check required",
    RESOLVED_MANUAL: "Manually resolved after device inspection",
    CANCELLED: "Cancelled before any change",
}


class InvalidTransition(Exception):
    """Raised for a state change the table does not allow."""


def can_transition(current: str, new: str) -> bool:
    return new in TRANSITIONS.get(current, frozenset())


def assert_transition(current: str, new: str) -> None:
    if current not in TRANSITIONS:
        raise InvalidTransition(f"unknown state {current!r}")
    if new not in TRANSITIONS:
        raise InvalidTransition(f"unknown state {new!r}")
    if not can_transition(current, new):
        raise InvalidTransition(f"transition {current} -> {new} is not allowed")


def is_terminal(state: str) -> bool:
    return state in TERMINAL_STATES


def transition_allowed_from(new: str) -> FrozenSet[str]:
    """The states a job may be in for the `WHERE status IN (...)` of an atomic UPDATE."""
    return frozenset(s for s, nxt in TRANSITIONS.items() if new in nxt)
