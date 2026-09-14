"""SDF-5 board-operations errors.

Base :class:`BoardOpError` covers everything this slice raises so callers
can catch the whole surface with one except clause. Machine errors
(:class:`BoardClosed`, :class:`UnknownHandle`, ...) are **re-exported, never
redefined**: the SDF-2 ``VerdictMachine`` stays the single authority for
verdict-state errors, and downstream code (SDF-6/7/10/11/18) can import the
whole error vocabulary from :mod:`server` without importing ``board.machine``
directly.
"""

from __future__ import annotations

from board.machine import (  # noqa: F401  (re-export is the point)
    BoardAlreadyExists,
    BoardClosed,
    GovernanceNotSettled,
    ModeSwitchNotSettled,
    NoBoard,
    NodeFrozen,
    NotActiveNode,
    VerdictError,
)


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
    """Registry-level ``(X, label)`` collision (defensive: ``open_board``
    treats a taken key as the get path)."""


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
    # re-exported from the SDF-2 machine
    "BoardClosed",
    "BoardAlreadyExists",
    "NoBoard",
    "NodeFrozen",
    "NotActiveNode",
    "VerdictError",
    "GovernanceNotSettled",
    "ModeSwitchNotSettled",
]
