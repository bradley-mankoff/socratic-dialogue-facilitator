"""AC1 back half + AC3 — ballot ingestion through the service.

Stories 16–18: explicit and ambient ballots ingest with one counted ballot
per person, explicit precedence in both arrival orders, the integer refute
predicate runs live on the frozen census (majority refutes, ties and
shortfalls do not, 1-human rooms decide), re-votes latest-count and may
un-refute the active node, and the events feed is journal-sourced.
"""

import json

import pytest

from board.machine import (
    NodeFrozen,
    QNotOpen,
    SideMismatch,
    UnknownHandle,
    UnknownQuestion,
)
import board.verdicts as V
from server.model import VOTE_EVENT_TYPES, VoteResult
from tests.sdf6_stubs import make_svc


def test_explicit_vote_ingests_and_counts(tmp_path):
    env = make_svc(tmp_path)
    service, bid, machine = env.service, env.board_id, env.machine
    result = service.cast_vote(bid, env.q, "stands", by_display="Cephalus",
                               reason="the ruler errs")
    assert isinstance(result, VoteResult)
    assert result.board_id == bid
    assert result.node_id == env.node
    assert result.ce_id == env.ce
    assert result.q_id == env.q
    assert result.handle_id == env.h["Cephalus"]
    assert result.display == "Cephalus"
    assert result.channel == "explicit"
    assert result.side == "stands"
    assert result.reason == "the ruler errs"
    assert result.counted is True
    assert result.replaced_ballot_id is None
    assert result.refuted is False          # 1 stands over census 3: 2 not > 3
    assert machine.standing_counts(env.ce) == (1, 0)
    assert machine.state.ballots[result.ballot_id].reason == result.reason


def test_ambient_hook_ingests_with_receive_time_ordering(tmp_path):
    env = make_svc(tmp_path)
    service, bid, machine = env.service, env.board_id, env.machine
    early = service.record_ambient_vote(bid, env.q, "stands",
                                        by_display="Cephalus",
                                        receive_time=1.0)
    late = service.record_ambient_vote(bid, env.q, "rebutted",
                                       by_display="Cephalus",
                                       receive_time=3.0)
    # later receive_time counts, no matter the call order
    counted = machine.counted(env.q, env.h["Cephalus"])
    assert counted.ballot_id == late.ballot_id and counted.side == "rebutted"

    # same clock, older receive_time: the transcript-later ballot loses...
    older = service.record_ambient_vote(bid, env.q, "stands",
                                        by_display="Cephalus",
                                        receive_time=3.0)
    counted = machine.counted(env.q, env.h["Cephalus"])
    assert counted.ballot_id == older.ballot_id, \
        "equal receive_time breaks by journal seq — insertion order wins"
    assert early.ballot_id != late.ballot_id


def test_explicit_beats_ambient_both_orders(tmp_path):
    env = make_svc(tmp_path)
    service, bid, machine = env.service, env.board_id, env.machine
    # ambient first, then explicit: one counted ballot, the explicit one
    ambient = service.record_ambient_vote(bid, env.q, "stands",
                                          by_display="Cephalus",
                                          receive_time=1.0)
    explicit = service.cast_vote(bid, env.q, "rebutted", by_display="Cephalus")
    counted = machine.counted(env.q, env.h["Cephalus"])
    assert counted.ballot_id == explicit.ballot_id
    assert counted.channel == "explicit"
    assert explicit.counted is True
    assert explicit.replaced_ballot_id == ambient.ballot_id
    # exactly one counted ballot for this handle
    assert machine.standing_counts(env.ce) == (0, 1)

    # explicit first, ambient later: the ambient is shadowed, never counted
    explicit2 = service.cast_vote(bid, env.q, "rebutted",
                                  by_display="Polemarchus", receive_time=1.0)
    shadowed = service.record_ambient_vote(bid, env.q, "stands",
                                           by_display="Polemarchus",
                                           receive_time=9.0)
    counted = machine.counted(env.q, env.h["Polemarchus"])
    assert counted.ballot_id == explicit2.ballot_id and counted.side \
        == "rebutted"
    assert shadowed.counted is False
    # Fused from panel a: a shadowed ambient replaces nothing — the
    # previously counted explicit keeps its place, so None (not the
    # explicit's id) is the only truthful `replaced_ballot_id`.
    assert shadowed.replaced_ballot_id is None
    assert machine.standing_counts(env.ce) == (0, 2)


def test_majority_of_frozen_census_refutes(tmp_path):
    env = make_svc(tmp_path)
    service, bid, machine = env.service, env.board_id, env.machine
    # census froze at open: the three enrolled humans; 2 stands refutes
    service.cast_vote(bid, env.q, "stands", by_display="Cephalus")
    service.cast_vote(bid, env.q, "stands", by_display="Polemarchus")
    service.cast_vote(bid, env.q, "rebutted", by_display="Thrasymachus")
    assert 2 * 2 > len(machine.census(env.q)) == 3
    assert machine.is_refuted(env.ce) is True
    assert machine.state.nodes[env.node].status == "refuted"
    assert service.scoreboard(bid)["is_refuted"] is True

    # a 4th human enrolled after open, casting nothing, never joins
    diotima = machine.enroll_handle("Diotima")
    assert diotima not in machine.census(env.q)
    assert machine.is_refuted(env.ce) is True

    # a late CASTED ballot joins the census: the arithmetic re-derives
    late = service.cast_vote(bid, env.q, "stands", handle_id=diotima,
                             receive_time=9.0)
    assert diotima in machine.census(env.q)
    assert len(machine.census(env.q)) == 4
    assert late.refuted is True              # 2*3 == 6 > 4 still refutes

    # now 2 stands / 2 rebutted over census 4: 4 not > 4, un-refuted
    flip = service.cast_vote(bid, env.q, "rebutted", by_display="Cephalus")
    assert flip.refuted is False
    assert machine.state.nodes[env.node].status == "unrefuted"
    # and 3–1 over census 4 refutes again (6 > 4)
    back = service.cast_vote(bid, env.q, "stands", by_display="Cephalus")
    assert back.refuted is True


def test_two_human_tie_stays_not_refuted(tmp_path):
    env = make_svc(tmp_path, humans=("Cephalus", "Polemarchus"))
    service, bid, machine = env.service, env.board_id, env.machine
    service.cast_vote(bid, env.q, "stands", by_display="Cephalus")
    service.cast_vote(bid, env.q, "rebutted", by_display="Polemarchus")
    # 1–1 true tie: the CE stands but refutation needs 2*1 > 2 — fails
    assert machine.is_standing(env.ce) is True
    assert machine.is_refuted(env.ce) is False
    assert service.scoreboard(bid)["is_refuted"] is False
    status, outcome = machine.q_status(env.q)
    assert (status, outcome) == ("open", None)
    row = service.scoreboard(bid)["ces"][0]
    assert row["outcome"] is None
    assert row["tie_exemption"] is None, "no exemption outside 1-human rooms"
    assert row["decisive_side"] is None


def test_single_handle_room_lone_vote_decides(tmp_path):
    env = make_svc(tmp_path, humans=("Thrasymachus",),
                   claimant="Thrasymachus", allege=False)
    service, bid, machine = env.service, env.board_id, env.machine
    alleged = service.allege(bid, "3a", by_display="Thrasymachus")
    human = env.h["Thrasymachus"]
    # census 1: the lone handle's stands vote refutes by strict majority
    service.cast_vote(bid, alleged.q_id, "stands", handle_id=human)
    row = service.scoreboard(bid)["ces"][0]
    assert row["tie_exemption"] is None, "one handle cannot tie"
    assert row["decisive_side"] is None
    assert machine.is_refuted(alleged.ce_id) is True

    # the same handle's word flips it: rebutted defeats the CE
    service.cast_vote(bid, alleged.q_id, "rebutted", handle_id=human)
    row = service.scoreboard(bid)["ces"][0]
    assert machine.is_refuted(alleged.ce_id) is False


def test_revote_latest_counts_and_can_unrefute_active_node(tmp_path):
    env = make_svc(tmp_path)
    service, bid, machine = env.service, env.board_id, env.machine
    service.cast_vote(bid, env.q, "stands", by_display="Cephalus")
    service.cast_vote(bid, env.q, "stands", by_display="Polemarchus")
    assert machine.is_refuted(env.ce) is True            # 2–0 over census 3
    # both re-vote: latest counts, and the ACTIVE node may un-refute
    service.cast_vote(bid, env.q, "rebutted", by_display="Cephalus")
    service.cast_vote(bid, env.q, "rebutted", by_display="Polemarchus")
    assert machine.is_refuted(env.ce) is False
    assert machine.state.nodes[env.node].status == "unrefuted"
    # every ballot still on record, one counted per handle
    assert len(machine.state.ballots) == 4
    assert len(V.counted(machine.state, env.q)) == 2
    assert machine.counted(env.q, env.h["Cephalus"]).side == "rebutted"


def test_retract_ambient_only_semantics(tmp_path):
    env = make_svc(tmp_path)
    service, bid, machine = env.service, env.board_id, env.machine
    first = service.record_ambient_vote(bid, env.q, "stands",
                                        by_display="Cephalus",
                                        receive_time=1.0)
    second = service.record_ambient_vote(bid, env.q, "rebutted",
                                         by_display="Cephalus",
                                         receive_time=2.0)
    assert machine.counted(env.q, env.h["Cephalus"]).ballot_id \
        == second.ballot_id
    retracted = service.retract_vote(bid, env.q, by_display="Cephalus")
    assert retracted["had_effect"] is True
    assert retracted["withdrawn_ballot_id"] == second.ballot_id
    assert retracted["display"] == "Cephalus"
    # the older ambient resurfaces and counts again
    counted = machine.counted(env.q, env.h["Cephalus"])
    assert counted.ballot_id == first.ballot_id
    assert machine.standing_counts(env.ce) == (1, 0)

    # retract again: withdraws the resurfaced ambient, nothing counts after
    again = service.retract_vote(bid, env.q, handle_id=env.h["Cephalus"])
    assert again["had_effect"] is True
    assert again["withdrawn_ballot_id"] == first.ballot_id
    assert machine.counted(env.q, env.h["Cephalus"]) is None
    # nothing left: retracting an empty handle is a no-op
    nothing = service.retract_vote(bid, env.q, by_display="Cephalus")
    assert nothing["had_effect"] is False
    assert nothing["withdrawn_ballot_id"] is None

    # an explicit vote is never retracted — changing it means re-casting
    service.cast_vote(bid, env.q, "stands", by_display="Polemarchus")
    explicit_retract = service.retract_vote(bid, env.q,
                                            by_display="Polemarchus")
    assert explicit_retract["had_effect"] is False
    assert machine.counted(env.q, env.h["Polemarchus"]).channel \
        == "explicit"


def test_frozen_node_and_frozen_q_refuse_votes(tmp_path):
    env = make_svc(tmp_path)
    service, bid, machine = env.service, env.board_id, env.machine
    service.cast_vote(bid, env.q, "stands", by_display="Cephalus")
    revised = service.revise(bid, "Justice is teaching what is good.",
                             claimant_display="Thrasymachus",
                             in_response_to=env.ce)
    # the superseded node's question is frozen: refusals pass through
    with pytest.raises(NodeFrozen):
        service.cast_vote(bid, env.q, "rebutted", by_display="Cephalus")
    with pytest.raises(QNotOpen):
        service.retract_vote(bid, env.q, by_display="Cephalus")
    # the ACTIVE node accepts votes: a fresh CE + a ballot on it
    fresh = service.allege(bid, "3b", by_display="Polemarchus")
    assert machine.state.ces[fresh.ce_id].node_id == revised.node_id
    result = service.cast_vote(bid, fresh.q_id, "stands",
                               by_display="Cephalus")
    assert result.node_id == revised.node_id


def test_side_vocabulary_guards(tmp_path):
    env = make_svc(tmp_path)
    service, bid, machine = env.service, env.board_id, env.machine
    with pytest.raises(SideMismatch):
        service.cast_vote(bid, env.q, "for", by_display="Cephalus")
    with pytest.raises(UnknownQuestion):
        service.cast_vote(bid, "q999", "stands", by_display="Cephalus")
    with pytest.raises(UnknownHandle):
        service.cast_vote(bid, env.q, "stands", handle_id="h99")
    # unknown q is refused before any handle enrollment
    handles = len(machine.state.handles)
    with pytest.raises(UnknownQuestion):
        service.record_ambient_vote(bid, "q999", "stands",
                                    by_display="Stranger")
    assert len(machine.state.handles) == handles
    # a voter is required: neither id nor display is a ValueError
    with pytest.raises(ValueError):
        service.cast_vote(bid, env.q, "stands")


def test_vote_result_roundtrip_and_events_feed(tmp_path):
    env = make_svc(tmp_path)
    service, bid, machine = env.service, env.board_id, env.machine
    r1 = service.cast_vote(bid, env.q, "stands", by_display="Cephalus",
                           reason="first read")
    r2 = service.record_ambient_vote(bid, env.q, "rebutted",
                                     by_display="Cephalus",
                                     receive_time=7.0)
    # retracting an explicit-only handle is a no-op: the explicit survives
    r3 = service.retract_vote(bid, env.q, handle_id=env.h["Cephalus"])
    assert json.loads(json.dumps(r1.to_dict())) == r1.to_dict()
    assert VoteResult.from_dict(r2.to_dict()) == r2
    assert r3["had_effect"] is False
    assert machine.counted(env.q, env.h["Cephalus"]).channel == "explicit"

    # an ambient retraction journals; the shadowed ballot never surfaces
    service.record_ambient_vote(bid, env.q, "stands", by_display="Polemarchus",
                                receive_time=1.0)
    r5 = service.retract_vote(bid, env.q, by_display="Polemarchus")
    assert r5["had_effect"] is True

    events = service.vote_events(bid)
    assert events == sorted(events, key=lambda e: e["seq"])
    assert set(e["type"] for e in events) <= set(VOTE_EVENT_TYPES)
    assert all(set(e) == {"seq", "type", "payload"} for e in events)
    assert [e["type"] for e in events] == [
        "ballot_cast",    # explicit stands (r1)
        "ballot_cast",    # ambient, shadowed by the explicit (r2)
        "ballot_cast",    # ambient stands (Polemarchus)
        "retraction",     # the counted ambient retracted (r5)
    ]
    assert events[0]["payload"]["ballot_id"] == r1.ballot_id
    assert events[1]["payload"]["channel"] == "ambient"
    # since_seq filters strictly: only events strictly after the cutoff
    assert [e["seq"] for e in service.vote_events(bid, since_seq=r1.seq)] \
        == [e["seq"] for e in events if e["seq"] > r1.seq]
    assert service.vote_events(bid, since_seq=10 ** 9) == []

    # reopen: the feed is a pure journal read, identical after reload
    from server.service import BoardService
    from tests.sdf5_stubs import empty_chain
    reopened = BoardService(tmp_path, chain=empty_chain())
    assert reopened.vote_events(bid) == events
    assert reopened.vote_events(bid, since_seq=r2.seq) == [
        e for e in events if e["seq"] > r2.seq]
