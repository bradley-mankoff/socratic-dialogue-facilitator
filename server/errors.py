"""SDF-5 board-operations errors."""

from __future__ import annotations


class BoardOpError(RuntimeError):
    """Base for every SDF-5 board-operations failure."""


class UnknownBoard(BoardOpError):
    """``board_id`` absent from the registry."""


class NoCanonicals(BoardOpError):
    """No cached snapshot for this X (canonical pull was deferred)."""


class EmptyCanonicals(BoardOpError):
    """The cached snapshot is the chain's explicit empty state."""


class UnknownSense(BoardOpError):
    """``sense_id`` not present in the cached snapshot."""


class NoActiveClaim(BoardOpError):
    """``revise()`` on a board with no claim to revise."""


class ClaimAlreadyActive(BoardOpError):
    """A second first-claim; the canonical path is :meth:`revise`."""


class BlankClaim(BoardOpError):
    """Claim text is not a non-blank string (machine would accept ``""``)."""


class DuplicateLabel(BoardOpError):
    """Registry-level ``(X, label)`` collision."""


class GovernanceAlreadyOpen(BoardOpError):
    """A unicast governance move (or one ingress candidate) is already an
    open question; the message names the existing ``q_id``."""


class GovernanceNoOp(BoardOpError):
    """The move would change nothing (same mode / already-active claim)."""


class NotAGovernanceQuestion(BoardOpError):
    """A governance-only call was aimed at a refutation question."""


__all__ = [
    "BoardOpError",
    "UnknownBoard",
    "NoCanonicals",
    "EmptyCanonicals",
    "UnknownSense",
    "NoActiveClaim",
    "ClaimAlreadyActive",
    "BlankClaim",
    "DuplicateLabel",
    "GovernanceAlreadyOpen",
    "GovernanceNoOp",
    "NotAGovernanceQuestion",
]
