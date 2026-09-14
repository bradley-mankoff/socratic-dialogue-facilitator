"""AC2 governance — the tiebreak-invoke protocol end to end (story 20).

A lost tie in facilitates mode: one invocation per CE ever, the invoke Q
settles on strict census majority (or the 1-human exemption), then the
facilitator lands exactly one labeled reasoned ballot, fixed ``rebutted``,
counting in the tally but taking no census seat.
"""

import json

import pytest

from board.machine import (
    BoardClosed,
    DuplicateTiebreak,
    NodeFrozen,
    TiebreakNotPassed,
    VerdictError,
)
from server.errors import UnknownCounterexample
from server.model import TiebreakResult
from tests.sdf6_stubs import make_svc


def test_invoke_requires_facilitates_and_once_per_ce(tmp_path):
    env = make_svc(tmp_path)
    # participates rooms never invoke tiebreaks
    with pytest.raises(VerdictError):
        env.service.invoke_tiebreak(env.board_id, env.ce,
                                    by_display="Cephalus")

    horn = make_svc(tmp_path / "horn", mode="facilitates", facilitator=True)
    service, bid = horn.service, horn.board_id
    result = service.invoke_tiebreak(bid, horn.ce, by_display="Cephalus")
    assert result.ce_id == horn.ce
    assert result.tiebreak_q_id != horn.q
    q = service.state(bid).questions[result.tiebreak_q_id]
    assert q.kind == "tiebreak" and q.status == "open"
    assert q.subject == horn.ce
    assert result.opened_by == horn.h["Cephalus"]
    assert result.opened_seq == q.opened_seq
    assert service.state(bid).ces[horn.ce].tiebreak_invoked is True

    # exactly one invocation per CE, ever
    with pytest.raises(DuplicateTiebreak):
        service.invoke_tiebreak(bid, horn.ce, by_display="Polemarchus")
    # unknown CE refuses before any enrollment
    handles = len(service.state(bid).handles)
    with pytest.raises(UnknownCounterexample):
        service.invoke_tiebreak(bid, "ce99")
    assert len(service.state(bid).handles) == handles

    # the result is JSON-exact and round-trips
    assert TiebreakResult.from_dict(result.to_dict()) == result
    assert json.loads(json.dumps(result.to_dict())) == result.to_dict()


def test_ballot_requires_settled_for_invoke(tmp_path):
    env = make_svc(tmp_path, mode="facilitates", facilitator=True)
    service, bid = env.service, env.board_id
    invoked = service.invoke_tiebreak(bid, env.ce, by_display="Cephalus")
    # the room votes the invocation DOWN: 2 against over census 3 settles
    service.cast_vote(bid, invoked.tiebreak_q_id, "against",
                      by_display="Cephalus")
    service.cast_vote(bid, invoked.tiebreak_q_id, "against",
                      by_display="Polemarchus")
    assert service.machine(bid).q_status(invoked.tiebreak_q_id) \
        == ("settled", "against")
    with pytest.raises(TiebreakNotPassed):
        service.cast_tiebreak_ballot(bid, env.ce, "still not empowered")

    # and a settled-for invoke still demands a real reason
    horn = make_svc(tmp_path / "horn", mode="facilitates", facilitator=True)
    horn.service.cast_vote(horn.board_id, horn.q, "stands",
                           by_display="Cephalus")
    horn.service.cast_vote(horn.board_id, horn.q, "rebutted",
                           by_display="Polemarchus")
    ok = horn.service.invoke_tiebreak(horn.board_id, horn.ce,
                                      by_display="Cephalus")
    horn.service.cast_vote(horn.board_id, ok.tiebreak_q_id, "for",
                           by_display="Cephalus")
    horn.service.cast_vote(horn.board_id, ok.tiebreak_q_id, "for",
                           by_display="Polemarchus")
    for blank in ("", "   ", None):
        with pytest.raises(ValueError):
            horn.service.cast_tiebreak_ballot(horn.board_id, horn.ce, blank)
    assert horn.service.state(horn.board_id).ces[horn.ce] \
        .tiebreak_ballot_id is None


def test_majority_invoke_then_single_labeled_ballot_flips_tie(tmp_path):
    env = make_svc(tmp_path, mode="facilitates", facilitator=True)
    service, bid, machine = env.service, env.board_id, env.machine
    service.cast_vote(bid, env.q, "stands", by_display="Cephalus")
    service.cast_vote(bid, env.q, "rebutted", by_display="Polemarchus")
    assert machine.standing_counts(env.ce) == (1, 1)
    assert machine.is_standing(env.ce) is True
    assert machine.is_refuted(env.ce) is False, "the tie stands"

    invoked = service.invoke_tiebreak(bid, env.ce, by_display="Cephalus")
    service.cast_vote(bid, invoked.tiebreak_q_id, "for",
                      by_display="Cephalus")
    service.cast_vote(bid, invoked.tiebreak_q_id, "for",
                      by_display="Polemarchus")
    assert machine.q_status(invoked.tiebreak_q_id) == ("settled", "for"), \
        "2 'for' over census 3 settles the invocation automatically"

    ballot = service.cast_tiebreak_ballot(bid, env.ce,
                                          "the example misapplies the term")
    assert ballot.ballot_id is not None
    assert ballot.channel == "explicit"
    assert ballot.side == "rebutted"
    assert ballot.reason == "the example misapplies the term"
    assert ballot.counted is True
    assert ballot.replaced_ballot_id is None
    assert ballot.handle_id == env.f
    assert ballot.display == "facilitator"
    stored = machine.state.ballots[ballot.ballot_id]
    assert stored.labeled is True and stored.channel == "explicit"

    # the labeled ballot counts in the tally but takes no census seat
    assert env.f not in machine.census(env.q)
    assert machine.standing_counts(env.ce) == (1, 2)
    assert machine.is_standing(env.ce) is False
    assert machine.is_refuted(env.ce) is False, \
        "still-not-refuted stays so; the tie lands on not-refuted"

    # one ballot per CE, ever
    with pytest.raises(DuplicateTiebreak):
        service.cast_tiebreak_ballot(bid, env.ce, "once more")
    with pytest.raises(DuplicateTiebreak):
        service.invoke_tiebreak(bid, env.ce, by_display="Cephalus")


def test_sync_registry_mirror_matches_live_after_votes(tmp_path):
    """The SDF-6 contract call site: sync_registry after exactly the four
    verdict-affecting mutators, so the registry mirror can never drift from
    the live machine state along the allege → vote → refute → tiebreak path.
    """
    env = make_svc(tmp_path, mode="facilitates", facilitator=True,
                   allege=False)
    service, bid, machine = env.service, env.board_id, env.machine
    alleged = service.allege(bid, "3a", by_display="Cephalus")
    record = service.board(bid)
    assert (record.mode, record.medium, record.status) \
        == (machine.state.mode, machine.state.medium, machine.state.status)

    # the four verdict-affecting mutators sync; allege did not need to
    service.cast_vote(bid, alleged.q_id, "stands", by_display="Polemarchus")
    service.cast_vote(bid, alleged.q_id, "rebutted", by_display="Thrasymachus")
    assert machine.is_refuted(alleged.ce_id) is False
    invoked = service.invoke_tiebreak(bid, alleged.ce_id,
                                      by_display="Cephalus")
    service.cast_vote(bid, invoked.tiebreak_q_id, "for",
                      by_display="Polemarchus")
    service.cast_vote(bid, invoked.tiebreak_q_id, "for",
                      by_display="Thrasymachus")
    ballot = service.cast_tiebreak_ballot(bid, alleged.ce_id, "tie lands safe")
    assert ballot.counted is True

    state = machine.state
    after = service.board(bid)
    assert (after.mode, after.medium, after.status) \
        == (state.mode, state.medium, state.status)
    assert after.board_id == bid and after.label == record.label
    # a read never syncs: scoreboard stays a pure projection
    _ = service.scoreboard(bid)
    assert service.board(bid) == after


def test_frozen_or_closed_refusals(tmp_path):
    env = make_svc(tmp_path, mode="facilitates", facilitator=True)
    service, bid, machine = env.service, env.board_id, env.machine
    service.cast_vote(bid, env.q, "stands", by_display="Cephalus")
    service.cast_vote(bid, env.q, "rebutted", by_display="Polemarchus")
    invoked = service.invoke_tiebreak(bid, env.ce, by_display="Cephalus")
    service.cast_vote(bid, invoked.tiebreak_q_id, "for", by_display="Cephalus")
    service.cast_vote(bid, invoked.tiebreak_q_id, "for",
                      by_display="Polemarchus")
    # the claim is revised in response: the CE's node is frozen, the
    # empowered ballot can no longer land
    service.revise(bid, "Justice is teaching what is good.",
                   claimant_display="Thrasymachus", in_response_to=env.ce)
    with pytest.raises(NodeFrozen):
        service.cast_tiebreak_ballot(bid, env.ce, "too late")
    with pytest.raises(NodeFrozen):
        service.cast_vote(bid, env.q, "stands", by_display="Cephalus")

    # a settled close ends the board: everything refuses afterwards.
    # 2 'for' over census 3 already settles the close Q and closes the board
    close_q = machine.open_governance_q("close", opened_by=env.h["Thrasymachus"])
    service.cast_vote(bid, close_q, "for", by_display="Cephalus")
    service.cast_vote(bid, close_q, "for", by_display="Polemarchus")
    assert machine.is_closed() is True
    with pytest.raises(BoardClosed):
        service.cast_vote(bid, close_q, "for", by_display="Thrasymachus")
    with pytest.raises(BoardClosed):
        service.invoke_tiebreak(bid, env.ce, by_display="Cephalus")
    with pytest.raises(BoardClosed):
        service.cast_tiebreak_ballot(bid, env.ce, "after hours")
    with pytest.raises(BoardClosed):
        service.cast_vote(bid, env.q, "stands", by_display="Cephalus")
