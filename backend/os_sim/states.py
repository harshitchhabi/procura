"""Process state machine definitions.

States mirror a textbook OS process lifecycle:
    NEW -> READY -> RUNNING -> (BLOCKED | COMPLETED)
    BLOCKED -> READY
    READY | RUNNING | BLOCKED -> TERMINATED
"""

from __future__ import annotations


class State:
    NEW = "NEW"
    READY = "READY"
    RUNNING = "RUNNING"
    BLOCKED = "BLOCKED"
    COMPLETED = "COMPLETED"
    TERMINATED = "TERMINATED"


ALL_STATES = {
    State.NEW,
    State.READY,
    State.RUNNING,
    State.BLOCKED,
    State.COMPLETED,
    State.TERMINATED,
}

# Adjacency list of legal transitions.
VALID_TRANSITIONS: dict[str, set[str]] = {
    State.NEW: {State.READY},
    State.READY: {State.RUNNING, State.TERMINATED},
    State.RUNNING: {State.BLOCKED, State.COMPLETED, State.TERMINATED, State.READY},
    State.BLOCKED: {State.READY, State.TERMINATED},
    State.COMPLETED: set(),
    State.TERMINATED: set(),
}


class InvalidTransitionError(Exception):
    """Raised when a process is asked to move to a state it cannot legally reach."""


def validate_transition(current: str, target: str) -> None:
    if current not in ALL_STATES:
        raise InvalidTransitionError(f"Unknown current state: {current!r}")
    if target not in ALL_STATES:
        raise InvalidTransitionError(f"Unknown target state: {target!r}")
    if target not in VALID_TRANSITIONS.get(current, set()):
        raise InvalidTransitionError(
            f"Cannot transition process from {current} to {target}. "
            f"Valid targets from {current}: {sorted(VALID_TRANSITIONS.get(current, set())) or 'none'}"
        )
