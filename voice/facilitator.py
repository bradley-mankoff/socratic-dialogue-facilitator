"""SDF-15 — facilitator voice modes (spec stories 23, 24, 25, 26).

Pure, headless, stdlib only. Every facilitator contribution is a labeled
post quoting the target id it responds to (story 24); META teaching
callouts are quota-capped — one per defender turn live, one per revision
node async — with extras mechanically dropped as moot, and zero META in
Facilitates rooms (story 23); a post quoting a moot target self-cuts and
never lands (story 25); ballots carry visible reasons at equal weight
(story 26); peer suggestions land only in Participates mode (story 27's
zero-voice Facilitates half).

Posts are transient poll/WebSocket feed items, never journal events: moot
posts are kept in the log with ``status="moot"`` for audit but excluded
from :meth:`FacilitatorVoice.feed`, which is what the transport reads.
"""

from __future__ import annotations

from dataclasses import dataclass

POST_TYPES: tuple[str, ...] = ("META", "ELENCHUS", "SUGGESTION", "BALLOT")
BALLOT_SIDES: tuple[str, ...] = ("stands", "rebutted", "for", "against")
MODES: tuple[str, ...] = ("participates", "facilitates")
MEDIA: tuple[str, ...] = ("async", "live")

POSTED = "posted"
MOOT = "moot"


@dataclass(frozen=True)
class FacilitatorPost:
    """One facilitator contribution: its type plus the quoted target id."""

    post_id: str
    kind: str
    target_id: str
    text: str
    status: str
    weight: int
    mode: str
    medium: str
    node_id: str | None = None
    turn_id: str | None = None
    reason: str | None = None
    side: str | None = None


class FacilitatorVoice:
    """Quota + staleness gate for facilitator posts on one board."""

    def __init__(self, mode: str = "participates",
                 medium: str = "async") -> None:
        if mode not in MODES:
            raise ValueError(f"mode must be one of {MODES}")
        if medium not in MEDIA:
            raise ValueError(f"medium must be one of {MEDIA}")
        self.mode = mode
        self.medium = medium
        self._posts: list[FacilitatorPost] = []
        self._meta_used: set[tuple] = set()
        self._moot_targets: set[str] = set()

    def mark_target_moot(self, target_id: str) -> None:
        """The quoted target went moot; later posts on it self-cut."""
        if not isinstance(target_id, str) or not target_id.strip():
            raise ValueError("target_id must be a non-blank string")
        self._moot_targets.add(target_id.strip())

    def post(self, kind: str, target_id: str, text: str = "",
             reason: str | None = None, node_id: str | None = None,
             turn_id: str | None = None,
             side: str | None = None) -> FacilitatorPost:
        """Label, quote, gate, and log one contribution.

        Raises :class:`ValueError` when the post lacks a type, a quoted
        target, its META quota key, or (for ballots) a visible reason.
        Otherwise returns the post with ``status`` ``"posted"`` or
        ``"moot"``; moot posts never land on :meth:`feed`.
        """
        if not isinstance(kind, str) or not kind.strip() \
                or kind.strip() not in POST_TYPES:
            raise ValueError(f"kind must be one of {POST_TYPES}")
        kind = kind.strip()
        if not isinstance(target_id, str) or not target_id.strip():
            raise ValueError("every facilitator post quotes its target id")
        target_id = target_id.strip()
        if kind == "BALLOT":
            if side is not None and side not in BALLOT_SIDES:
                raise ValueError(
                    f"ballot side must be one of {BALLOT_SIDES}")
            if not isinstance(reason, str) or not reason.strip():
                raise ValueError(
                    "facilitator ballots post a visible reason")
            reason = reason.strip()
        if target_id in self._moot_targets:
            return self._log(kind, target_id, text, MOOT, node_id, turn_id,
                             reason, side)
        if kind == "META":
            return self._log(kind, target_id, text,
                             self._meta_status(node_id, turn_id),
                             node_id, turn_id, reason, side)
        if kind == "SUGGESTION" and self.mode != "participates":
            return self._log(kind, target_id, text, MOOT, node_id, turn_id,
                             reason, side)
        return self._log(kind, target_id, text, POSTED, node_id, turn_id,
                         reason, side)

    def ballot(self, target_id: str, side: str, reason: str,
               text: str = "", node_id: str | None = None,
               turn_id: str | None = None) -> FacilitatorPost:
        """One transparent reasoned ballot at equal weight (story 26)."""
        if side not in BALLOT_SIDES:
            raise ValueError(f"ballot side must be one of {BALLOT_SIDES}")
        if not isinstance(reason, str) or not reason.strip():
            raise ValueError("facilitator ballots post a visible reason")
        return self.post("BALLOT", target_id, text, reason=reason,
                         node_id=node_id, turn_id=turn_id, side=side)

    def feed(self) -> list[FacilitatorPost]:
        """Posted contributions only — the poll/WebSocket payload.

        Moot posts are logged but never land, so a lagging or over-quota
        facilitator is never mistaken for commenting on the latest words.
        """
        return [p for p in self._posts if p.status == POSTED]

    def log(self) -> list[FacilitatorPost]:
        """Every contribution, posted and moot, in post order (audit)."""
        return list(self._posts)

    # -- internals --------------------------------------------------------

    def _meta_status(self, node_id: str | None,
                     turn_id: str | None) -> str:
        if self.mode != "participates":
            return MOOT
        if self.medium == "live":
            if not isinstance(node_id, str) or not node_id.strip():
                raise ValueError("live META needs its revision node id")
            if not isinstance(turn_id, str) or not turn_id.strip():
                raise ValueError("live META needs its defender turn id")
            key = (node_id.strip(), turn_id.strip())
        else:
            if not isinstance(node_id, str) or not node_id.strip():
                raise ValueError("async META needs its revision node id")
            key = (node_id.strip(),)
        if key in self._meta_used:
            return MOOT
        self._meta_used.add(key)
        return POSTED

    def _log(self, kind: str, target_id: str, text: str, status: str,
             node_id: str | None, turn_id: str | None,
             reason: str | None, side: str | None) -> FacilitatorPost:
        post = FacilitatorPost(
            post_id=f"f{len(self._posts) + 1}",
            kind=kind, target_id=target_id, text=text, status=status,
            weight=1 if kind == "BALLOT" else 0,
            mode=self.mode, medium=self.medium,
            node_id=node_id, turn_id=turn_id, reason=reason, side=side,
        )
        self._posts.append(post)
        return post


__all__ = [
    "POST_TYPES", "BALLOT_SIDES", "POSTED", "MOOT",
    "FacilitatorPost", "FacilitatorVoice",
]
