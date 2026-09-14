"""SDF-2 pure verdict predicates — no IO, no mutation.

Every function is a deterministic, side-effect-free function of a
``BoardState``, so the same code drives live verdicts and journal-replay
verdicts. Unknown ids raise ``KeyError`` (the machine wraps them in
domain exceptions).
"""

from __future__ import annotations

from board.model import BoardState, Ballot

# Fused alias from panel c: the per-question franchise set a verdict is
# computed over. Plain set of handle ids (see census()/board_census()).
BoardCensus = frozenset[str]


def human_handles(state: BoardState) -> list[str]:
    """Every handle that is not the facilitator seat, in enrollment order."""
    return [h.handle_id for h in state.handles.values() if not h.is_facilitator]


def _facilitator_handles(state: BoardState) -> list[str]:
    return [h.handle_id for h in state.handles.values() if h.is_facilitator]


def franchise(state: BoardState) -> list[str]:
    """Handles enfranchised right now, in enrollment order (fused from c).

    Everyone, plus the facilitator seat in participates mode only. This is
    what a question freezes as its open roster; ``board_census`` snapshots it.
    """
    return [
        h.handle_id
        for h in state.handles.values()
        if not (h.is_facilitator and state.mode != "participates")
    ]


def board_census(state: BoardState) -> BoardCensus:
    """Whole-board franchise snapshot (fused from c; SDF-8 governance reads this)."""
    return frozenset(franchise(state))


def census(state: BoardState, q_id: str) -> frozenset[str]:
    """Open roster (frozen at Q open, mode-adjusted) UNION every handle with
    a non-withdrawn, non-tiebreak counted ballot on this Q.

    Late non-voters never enter. The labeled facilitator tiebreak ballot is
    a tally vote but takes no census seat (the facilitator holds no
    franchise in facilitates mode).
    """
    q = state.questions[q_id]
    members = set(q.open_roster)
    for ballot in state.ballots.values():
        if ballot.q_id != q_id or ballot.withdrawn:
            continue
        if ballot.labeled:
            continue
        if counted_ballot(state, q_id, ballot.handle_id) is None:
            continue
        members.add(ballot.handle_id)
    return frozenset(members)


def counted_ballot(state: BoardState, q_id: str, handle_id: str) -> Ballot | None:
    """The one ballot that counts for (handle, Q).

    Latest EXPLICIT by (receive_time, seq) if any explicit exists, else
    latest AMBIENT. Withdrawn (mode-switch / retraction) ballots are
    invisible. Returns None when nothing counts.
    """
    explicit: list[Ballot] = []
    ambient: list[Ballot] = []
    for b in state.ballots.values():
        if b.q_id != q_id or b.handle_id != handle_id or b.withdrawn:
            continue
        (explicit if b.channel == "explicit" else ambient).append(b)
    pool = explicit if explicit else ambient
    if not pool:
        return None
    return max(pool, key=lambda b: (b.receive_time, b.seq))


def counted(state: BoardState, q_id: str) -> dict[str, Ballot]:
    """Every counted ballot on a question, keyed by handle (fused from c)."""
    if q_id not in state.questions:
        raise KeyError(q_id)
    out: dict[str, Ballot] = {}
    seen: set[str] = set()
    for b in state.ballots.values():
        if b.q_id == q_id and b.handle_id not in seen:
            seen.add(b.handle_id)
            cb = counted_ballot(state, q_id, b.handle_id)
            if cb is not None:
                out[b.handle_id] = cb
    return out


def _side_counts(pool: list[Ballot]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for b in pool:
        counts[b.side] = counts.get(b.side, 0) + 1
    return counts


def tally(state: BoardState, q_id: str) -> dict[str, int]:
    """Counted ballots by side for a refutation Q: {"stands", "rebutted"}.
    One vote per (handle, Q) — only the handle's single counted ballot."""
    q = state.questions[q_id]
    if q.kind != "refutation":
        raise ValueError(f"tally() is for refutation Qs, not {q.kind}")
    counts = {"stands": 0, "rebutted": 0}
    for handle_id in _ballot_handles(state, q_id):
        cb = counted_ballot(state, q_id, handle_id)
        if cb is not None:
            counts[cb.side] += 1
    return counts


def gov_tally(state: BoardState, q_id: str) -> dict[str, int]:
    """Counted ballots by side for a governance Q: {"for", "against"}."""
    q = state.questions[q_id]
    if q.kind == "refutation":
        raise ValueError("gov_tally() is for governance Qs, not refutation")
    counts = {"for": 0, "against": 0}
    for handle_id in _ballot_handles(state, q_id):
        cb = counted_ballot(state, q_id, handle_id)
        if cb is not None:
            counts[cb.side] += 1
    return counts


def _ballot_handles(state: BoardState, q_id: str) -> list[str]:
    """Distinct handles holding any non-withdrawn ballot on this Q."""
    seen: list[str] = []
    for b in state.ballots.values():
        if b.q_id == q_id and not b.withdrawn and b.handle_id not in seen:
            seen.append(b.handle_id)
    return seen


def standing_counts(state: BoardState, ce_id: str) -> tuple[int, int]:
    """(stands, rebutted) counted ballots on the CE's refutation Q."""
    ce = state.ces[ce_id]
    t = tally(state, ce.q_id)
    return t["stands"], t["rebutted"]


def standing_counts_from_q(state: BoardState, q_id: str) -> tuple[int, int]:
    """(stands, rebutted) directly from a refutation Q id (fused from c)."""
    t = tally(state, q_id)
    return t["stands"], t["rebutted"]


def has_strict_majority(census_size: int, votes_for: int,
                        votes_against: int) -> bool:
    """Strict census majority: votes_for * 2 > census_size AND
    votes_for > votes_against. Ties, halves (2*for == census) and
    shortfalls all fail."""
    return votes_for * 2 > census_size and votes_for > votes_against


def _tie(state: BoardState, q_id: str) -> bool:
    """True tie among the top two counts (equal and non-zero)."""
    q = state.questions[q_id]
    if q.kind == "refutation":
        t = tally(state, q_id)
        a, b = t["stands"], t["rebutted"]
    else:
        t = gov_tally(state, q_id)
        a, b = t["for"], t["against"]
    return a == b and a > 0


def tie_exemption_handle(state: BoardState, q_id: str) -> str | None:
    """The 1-human exception, scoped to true ties only.

    Active iff the whole board holds exactly ONE human handle
    (is_facilitator False), that human has a counted ballot on this Q, and
    the top two counts tie. The returned handle's ballot is decisive.
    Shortfalls never qualify.
    """
    humans = human_handles(state)
    if len(humans) != 1:
        return None
    h = humans[0]
    if counted_ballot(state, q_id, h) is None:
        return None
    if not _tie(state, q_id):
        return None
    return h


def _exempt_side(state: BoardState, q_id: str) -> str | None:
    h = tie_exemption_handle(state, q_id)
    if h is None:
        return None
    b = counted_ballot(state, q_id, h)
    return b.side if b is not None else None


def decisive_side(state: BoardState, q_id: str) -> str | None:
    """Side the single voting human takes when the tie exemption applies

    (fused from c; public alias of the fused ``_exempt_side``). None when
    the 1-human exception is not active on this Q.
    """
    return _exempt_side(state, q_id)


def is_standing(state: BoardState, ce_id: str) -> bool:
    """The CE stands: not defeated by rebuttals (ties stand), 0-0 does not.

    Under the 1-human exception the human's word overrides the ratio: a
    "rebutted" human ballot defeats the CE even on a 1-1 tie.
    """
    ce = state.ces[ce_id]
    q_id = ce.q_id
    exempt_side = _exempt_side(state, q_id)
    if exempt_side is not None:
        return exempt_side == "stands"
    t = tally(state, q_id)
    if t["stands"] == 0 and t["rebutted"] == 0:
        return False
    return t["stands"] >= t["rebutted"]


def ce_is_refuted(state: BoardState, ce_id: str) -> bool:
    """CE-level refute predicate (fused from c, adapted to fused semantics).

    Standing uses the fused rule (ties stand, 0-0 does not) and refutation
    needs 2*stands > |census| — except under the 1-human exception, where
    the single human's ballot is decisive and overrides the arithmetic.
    """
    ce = state.ces[ce_id]
    exempt_side = _exempt_side(state, ce.q_id)
    if exempt_side is not None:
        return exempt_side == "stands"
    t = tally(state, ce.q_id)
    if t["stands"] == 0 and t["rebutted"] == 0:
        return False
    if t["stands"] < t["rebutted"]:
        return False
    # ties stand but never refute without the exemption (strict majority
    # already encodes the tie/shortfall failure); keep the explicit guard
    # so the intent survives future arithmetic edits.
    if t["stands"] == t["rebutted"]:
        return False
    return 2 * t["stands"] > len(census(state, ce.q_id))


def is_refuted(state: BoardState, node_id: str) -> bool:
    """Some attached CE is standing AND refutes the claim.

    Refutation needs 2*stands > |census(ce.q_id)| (ties, halves and
    shortfalls fail) — except under the 1-human exception, where the
    single human's ballot is decisive and overrides the arithmetic.
    """
    node = state.nodes[node_id]
    # Delegates to the fused CE-level predicate so node/CE verdicts cannot drift.
    return any(ce_is_refuted(state, ce_id) for ce_id in node.ce_ids)


def refutation_outcome(state: BoardState, ce_id: str) -> str | None:
    """Effective winner of the CE's refutation Q: "stands" under strict
    majority (or the 1-human exemption), "rebutted" under the exemption,
    else None."""
    ce = state.ces[ce_id]
    exempt_side = _exempt_side(state, ce.q_id)
    if exempt_side is not None:
        return exempt_side
    t = tally(state, ce.q_id)
    if has_strict_majority(len(census(state, ce.q_id)),
                           t["stands"], t["rebutted"]):
        return "stands"
    return None


def governance_passed(state: BoardState, q_id: str) -> str | None:
    """Winning side ("for"/"against") under strict majority, else the
    tie-exempted human's side on a true tie, else None (stays open)."""
    q = state.questions[q_id]
    if q.kind == "refutation":
        raise ValueError("governance_passed() is for governance Qs")
    t = gov_tally(state, q_id)
    n = len(census(state, q_id))
    if has_strict_majority(n, t["for"], t["against"]):
        return "for"
    if has_strict_majority(n, t["against"], t["for"]):
        return "against"
    return _exempt_side(state, q_id)