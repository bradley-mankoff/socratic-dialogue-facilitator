"""SDF-2 pure verdict predicates — no IO, no mutation.

Every function is a deterministic, side-effect-free function of a
``BoardState``, so the same code drives live verdicts and journal-replay
verdicts. Unknown ids raise ``KeyError`` (the machine wraps them in
domain exceptions).
"""

from __future__ import annotations

from board.model import BoardState, Ballot, sides_for


def franchise(state: BoardState) -> list[str]:
    """Handles enfranchised right now, in enrollment order.

    Everyone: every handle counts the same in every question.
    """
    return [h.handle_id for h in state.handles.values()]


def census(state: BoardState, q_id: str) -> frozenset[str]:
    """Open roster (frozen at Q open) UNION every handle with
    a non-withdrawn counted ballot on this Q.

    Late non-voters never enter.
    """
    q = state.questions[q_id]
    members = set(q.open_roster)
    for ballot in state.ballots.values():
        if ballot.q_id != q_id or ballot.withdrawn:
            continue
        if counted_ballot(state, q_id, ballot.handle_id) is None:
            continue
        members.add(ballot.handle_id)
    return frozenset(members)


def counted_ballot(state: BoardState, q_id: str, handle_id: str) -> Ballot | None:
    """The one ballot that counts for (handle, Q).

    Latest EXPLICIT by (receive_time, seq) if any explicit exists, else
    latest AMBIENT. Withdrawn (retraction) ballots are
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
    """Every counted ballot on a question, keyed by handle."""
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


def tally(state: BoardState, q_id: str) -> dict[str, int]:
    """Counted ballots by side, keyed on the question kind's vocabulary."""
    q = state.questions[q_id]
    sides = sides_for(q.kind)
    counts = {side: 0 for side in sides}
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


def has_strict_majority(census_size: int, votes_for: int,
                        votes_against: int) -> bool:
    """Strict census majority: votes_for * 2 > census_size AND
    votes_for > votes_against. Ties, halves (2*for == census) and
    shortfalls all fail."""
    return votes_for * 2 > census_size and votes_for > votes_against


def _tie(state: BoardState, q_id: str) -> bool:
    """True tie among the top two counts (equal and non-zero)."""
    t = tally(state, q_id)
    a, b = t[sides_for(state.questions[q_id].kind)[0]], t[sides_for(state.questions[q_id].kind)[1]]
    return a == b and a > 0


def tie_exemption_handle(state: BoardState, q_id: str) -> str | None:
    """The 1-human exception, scoped to true ties only.

    Active iff the whole board holds exactly one handle, that handle has a counted ballot on this Q, and
    the top two counts tie. The returned handle's ballot is decisive.
    Shortfalls never qualify.

    Dormant since the sdf-zj6.1 cut removed the facilitator seat: with one
    handle a true tie is impossible (one counted ballot at most), so this
    always returns None until a later Spec adds a second voter. The Spec's
    AI player joins as an ordinary participant marked as the AI; when it
    lands, tell human handles apart from it here so the exception applies
    to exactly-one-human boards again.
    """
    handles = franchise(state)
    if len(handles) != 1:
        return None
    h = handles[0]
    if counted_ballot(state, q_id, h) is None:
        return None
    if not _tie(state, q_id):
        return None
    return h


def decisive_side(state: BoardState, q_id: str) -> str | None:
    """Side the single voting human takes when the tie exemption applies.

    None when the 1-human exception is not active on this Q.
    """
    h = tie_exemption_handle(state, q_id)
    if h is None:
        return None
    b = counted_ballot(state, q_id, h)
    return b.side if b is not None else None


def is_standing(state: BoardState, ce_id: str) -> bool:
    """The CE stands: not defeated by rebuttals (ties stand), 0-0 does not.

    Under the 1-human exception the human's word overrides the ratio: a
    "rebutted" human ballot defeats the CE even on a 1-1 tie.
    """
    ce = state.ces[ce_id]
    q_id = ce.q_id
    exempt_side = decisive_side(state, q_id)
    if exempt_side is not None:
        return exempt_side == "stands"
    t = tally(state, q_id)
    if t["stands"] == 0 and t["rebutted"] == 0:
        return False
    return t["stands"] >= t["rebutted"]


def ce_is_refuted(state: BoardState, ce_id: str) -> bool:
    """CE-level refute predicate."""
    return refutation_outcome(state, ce_id) == "stands"


def is_refuted(state: BoardState, node_id: str) -> bool:
    """Some attached CE is standing AND refutes the claim.

    Refutation needs 2*stands > |census(ce.q_id)| (ties, halves and
    shortfalls fail) — except under the 1-human exception, where the
    single human's ballot is decisive and overrides the arithmetic.
    """
    node = state.nodes[node_id]
    return any(ce_is_refuted(state, ce_id) for ce_id in node.ce_ids)


def refutation_outcome(state: BoardState, ce_id: str) -> str | None:
    """Effective winner of the CE's refutation Q: "stands" under strict
    majority (or the 1-human exemption), "rebutted" under the exemption,
    else None."""
    ce = state.ces[ce_id]
    exempt_side = decisive_side(state, ce.q_id)
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
    t = tally(state, q_id)
    n = len(census(state, q_id))
    if has_strict_majority(n, t["for"], t["against"]):
        return "for"
    if has_strict_majority(n, t["against"], t["for"]):
        return "against"
    return decisive_side(state, q_id)
