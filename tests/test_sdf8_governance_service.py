"""SDF-8 AC1/AC3 — governance moves through the service + close semantics.

Every move is a strict-majority Q owned by the SDF-2 machine; the service
only validates the room rules the machine leaves to callers, opens the Q,
mirrors mode/status effects, and logs. Close freezes tallies, snapshots the
unresolved tray and ends input. Headless, stubbed chain, no network.
"""

from types import SimpleNamespace

import pytest

from board.machine import (
    BoardClosed,
    SideMismatch,
    UnknownHandle,
    UnknownNode,
    UnknownQuestion,
)
from server.errors import (
    GovernanceAlreadyOpen,
    GovernanceNoOp,
    NotAGovernanceQuestion,
)
from server.store import GOVERNANCE_OPENED, GOVERNANCE_SETTLED
from tests.sdf5_stubs import JUSTICE, THRASYMACHUS, make_service

HANDLES = ("Cephalus", "Polemarchus", "Thrasymachus", "Cleitophon")
VOTERS = ("Cephalus", "Polemarchus", "Thrasymachus")


def governance_board(root, *, mode="participates", humans=HANDLES,
                     facilitator=True, claim=True):
    """Board on ``root`` with handles enrolled and (optionally) a claim."""
    svc = make_service(root)
    opened = svc.open_board(JUSTICE, pull_canonicals=False, mode=mode)
    board_id = opened.board_id
    machine = svc.machine(board_id)
    h = {name: machine.enroll_handle(name) for name in humans}
    f = (machine.enroll_handle("daimon", is_facilitator=True)
         if facilitator else None)
    if claim:
        svc.claim_original(board_id, THRASYMACHUS,
                           claimant_display=humans[0])
    return SimpleNamespace(service=svc, board_id=board_id, machine=machine,
                           h=h, f=f)


def _vote(svc, env, q_id, side):
    for name in VOTERS:
        svc.cast_vote(env.board_id, q_id, side, handle_id=env.h[name])


def _open_move(svc, env, kind):
    h1 = env.h["Cephalus"]
    if kind == "close":
        return svc.propose_close(env.board_id, opened_by=h1)
    if kind == "mode_switch":
        return svc.propose_mode_switch(env.board_id, "facilitates",
                                       opened_by=h1)
    if kind == "socrates_swap":
        return svc.propose_socrates_swap(env.board_id, env.h["Polemarchus"],
                                         opened_by=h1)
    if kind == "active_claim_switch":
        return svc.propose_active_claim_switch(env.board_id, "n1",
                                               opened_by=h1)
    raise AssertionError(kind)


def _settled_row(svc, board_id, q_id):
    rows = [e["payload"] for e in svc.read_system_log(
        board_id, GOVERNANCE_SETTLED) if e["payload"]["q_id"] == q_id]
    assert len(rows) == 1, f"expected exactly one settled row for {q_id}"
    return rows[0]


# -- AC1: each move passes by majority and logs as a system event ----------


def test_mode_switch_settles_and_applies_with_withdrawal(tmp_path):
    env = governance_board(tmp_path)
    svc, bid, m = env.service, env.board_id, env.machine
    h = env.h

    # a facilitator ballot on an OPEN refutation Q must be withdrawn when
    # the room leaves participates mode
    ce, qref = m.open_refutation_q("n1", "3a", opened_by=h["Cephalus"])
    svc.cast_vote(bid, qref, "stands", handle_id=env.f)
    svc.cast_vote(bid, qref, "rebutted", handle_id=h["Cephalus"])
    assert env.f in m.census(qref)

    ingress = svc.propose_ingress_selection(bid, "candidate-x",
                                            opened_by=h["Cephalus"])
    _vote(svc, env, ingress, "for")
    assert m.q_status(ingress) == ("settled", "for")   # history to keep

    q = svc.propose_mode_switch(bid, "facilitates", opened_by=h["Cephalus"])
    _vote(svc, env, q, "for")

    assert m.q_status(q) == ("settled", "for")
    assert m.state.mode == "facilitates"
    assert svc.board(bid).mode == "facilitates"        # registry mirror
    assert m.counted(qref, env.f) is None              # withdrawn
    assert env.f not in m.census(qref)
    applied = [e for e in m.events if e["type"] == "mode_switch_applied"]
    assert applied and applied[-1]["payload"]["withdrawn_ballot_ids"]
    assert m.q_status(ingress) == ("settled", "for")   # settled untouched

    opened = svc.read_system_log(bid, GOVERNANCE_OPENED)
    assert [e["payload"]["q_id"] for e in opened] == [ingress, q]
    row = _settled_row(svc, bid, q)
    assert row["origin"] == "system"
    assert row["kind"] == "mode_switch"
    assert row["subject"] == "facilitates"
    assert row["outcome"] == "for"
    assert row["tally"] == {"for": 3, "against": 0}
    assert row["census_size"] == 5
    status = svc.governance_status(bid, q)
    assert status["status"] == "settled"
    assert status["tally"] == {"for": 3, "against": 0}


def test_rejected_mode_switch_logs_against_and_changes_nothing(tmp_path):
    env = governance_board(tmp_path)
    svc, bid, m = env.service, env.board_id, env.machine
    q = svc.propose_mode_switch(bid, "facilitates", opened_by=env.h["Cephalus"])
    _vote(svc, env, q, "against")
    assert m.q_status(q) == ("settled", "against")
    assert m.state.mode == "participates"
    assert svc.board(bid).mode == "participates"
    assert not [e for e in m.events if e["type"] == "mode_switch_applied"]
    row = _settled_row(svc, bid, q)
    assert row["outcome"] == "against"
    assert row["tally"] == {"for": 0, "against": 3}


def test_socrates_swap_records_mandate_without_touching_seat(tmp_path):
    env = governance_board(tmp_path)
    svc, bid, m = env.service, env.board_id, env.machine
    m.set_socrates(env.h["Cephalus"])
    q = svc.propose_socrates_swap(bid, env.h["Polemarchus"],
                                  opened_by=env.h["Cephalus"])
    _vote(svc, env, q, "for")
    assert m.q_status(q) == ("settled", "for")
    # SDF-9 owns seats: this slice records the mandate, never moves it
    assert m.state.socrates_handle_id == env.h["Cephalus"]
    mandate = svc.mandate_for(bid, "socrates_swap")
    assert mandate["target"] == env.h["Polemarchus"]
    assert mandate["q_id"] == q
    assert _settled_row(svc, bid, q)["subject"] == env.h["Polemarchus"]


def test_later_rejected_swap_does_not_revoke_live_mandate(tmp_path):
    env = governance_board(tmp_path)
    svc, bid, m = env.service, env.board_id, env.machine
    first = svc.propose_socrates_swap(bid, env.h["Polemarchus"],
                                      opened_by=env.h["Cephalus"])
    _vote(svc, env, first, "for")
    second = svc.propose_socrates_swap(bid, env.h["Thrasymachus"],
                                       opened_by=env.h["Cephalus"])
    _vote(svc, env, second, "against")
    assert m.q_status(second) == ("settled", "against")
    mandate = svc.mandate_for(bid, "socrates_swap")
    assert mandate["target"] == env.h["Polemarchus"]
    assert mandate["q_id"] == first


def test_active_claim_switch_records_without_reactivating(tmp_path):
    env = governance_board(tmp_path)
    svc, bid, m = env.service, env.board_id, env.machine
    svc.revise(bid, "Justice is the interest of the stronger (v2).",
               claimant_display="Cephalus")
    assert m.state.active_node_id == "n2"

    q = svc.propose_active_claim_switch(bid, "n1",
                                        opened_by=env.h["Cephalus"])
    _vote(svc, env, q, "for")
    assert m.q_status(q) == ("settled", "for")
    assert m.state.active_node_id == "n2"          # never re-activated here
    mandate = svc.mandate_for(bid, "active_claim_switch")
    assert mandate["target"] == "n1"
    assert mandate["q_id"] == q

    with pytest.raises(GovernanceNoOp):
        svc.propose_active_claim_switch(bid, "n2",
                                        opened_by=env.h["Cephalus"])
    with pytest.raises(UnknownNode):
        svc.propose_active_claim_switch(bid, "n9",
                                        opened_by=env.h["Cephalus"])


def test_ingress_selection_multicast_and_mandate(tmp_path):
    env = governance_board(tmp_path)
    svc, bid, m = env.service, env.board_id, env.machine
    h1 = env.h["Cephalus"]
    qa = svc.propose_ingress_selection(bid, "candidate-a", opened_by=h1)
    qb = svc.propose_ingress_selection(bid, "candidate-b", opened_by=h1)
    assert m.q_status(qa) == ("open", None)
    assert m.q_status(qb) == ("open", None)

    with pytest.raises(GovernanceAlreadyOpen) as exc:
        svc.propose_ingress_selection(bid, "candidate-a", opened_by=h1)
    assert qa in str(exc.value)
    with pytest.raises(ValueError):
        svc.propose_ingress_selection(bid, "   ", opened_by=h1)

    _vote(svc, env, qb, "for")
    assert m.q_status(qb) == ("settled", "for")
    mandate = svc.mandate_for(bid, "ingress_selection")
    assert mandate["target"] == "candidate-b"
    assert mandate["q_id"] == qb
    assert mandate["consumer"] == "ingress"


def test_majority_boundaries_and_tie_exemption(tmp_path):
    env = governance_board(tmp_path / "majority")
    svc, bid, m = env.service, env.board_id, env.machine
    h = env.h
    q = svc.propose_ingress_selection(bid, "cand", opened_by=h["Cephalus"])
    svc.cast_vote(bid, q, "for", handle_id=h["Cephalus"])
    assert m.q_status(q) == ("open", None)          # 1/5
    svc.cast_vote(bid, q, "for", handle_id=h["Polemarchus"])
    assert m.q_status(q) == ("open", None)          # 2/5: 4 not > 5
    assert svc.read_system_log(bid, GOVERNANCE_SETTLED) == []

    svc.cast_vote(bid, q, "for", handle_id=h["Thrasymachus"])
    assert m.q_status(q) == ("settled", "for")      # 3/5: 6 > 5
    assert len(svc.read_system_log(bid, GOVERNANCE_SETTLED)) == 1

    # 1-human board: a 1-1 true tie is decided by the single human's side
    env1 = governance_board(tmp_path / "tie", humans=("Solo",),
                            facilitator=True)
    svc1, bid1, m1 = env1.service, env1.board_id, env1.machine
    q1 = svc1.propose_ingress_selection(bid1, "cand",
                                        opened_by=env1.h["Solo"])
    svc1.cast_vote(bid1, q1, "for", handle_id=env1.h["Solo"])
    assert m1.q_status(q1) == ("open", None)        # 1 for / census 2
    svc1.cast_vote(bid1, q1, "against", handle_id=env1.f)
    assert m1.q_status(q1) == ("settled", "for")    # exemption
    assert svc1.read_system_log(bid1, GOVERNANCE_SETTLED)


@pytest.mark.parametrize("kind", ["close", "mode_switch", "socrates_swap",
                                  "active_claim_switch"])
def test_duplicate_open_refused_per_kind_and_slot_freed(tmp_path, kind):
    env = governance_board(tmp_path)
    svc, m = env.service, env.machine
    if kind == "active_claim_switch":
        svc.revise(env.board_id, "Justice is the stronger's advantage.",
                   claimant_display="Cephalus")
    first = _open_move(svc, env, kind)
    with pytest.raises(GovernanceAlreadyOpen) as exc:
        _open_move(svc, env, kind)
    assert first in str(exc.value)
    _vote(svc, env, first, "against")
    assert m.q_status(first) == ("settled", "against")
    again = _open_move(svc, env, kind)
    assert m.q_status(again) == ("open", None)      # slot freed


# -- vote surface (AC1/AC2 plumbing) ---------------------------------------


def test_vote_refuses_refutation_qs_and_wrong_sides(tmp_path):
    env = governance_board(tmp_path)
    svc, bid, m = env.service, env.board_id, env.machine
    h1 = env.h["Cephalus"]
    ce, qref = m.open_refutation_q("n1", "3a", opened_by=h1)
    with pytest.raises(NotAGovernanceQuestion):
        svc.governance_vote(bid, qref, h1, "for")

    qg = svc.propose_ingress_selection(bid, "cand", opened_by=h1)
    with pytest.raises(SideMismatch):
        svc.governance_vote(bid, qg, h1, "stands")
    with pytest.raises(UnknownQuestion):
        svc.governance_vote(bid, "q999", h1, "for")

    handles_before = set(m.state.handles)
    ballots_before = len(m.state.ballots)
    with pytest.raises(UnknownHandle):
        svc.governance_vote(bid, qg, "h999", "for")
    assert set(m.state.handles) == handles_before   # no auto-enroll
    assert len(m.state.ballots) == ballots_before

    # explicit ballots are never retracted by the ambient-only path
    svc.record_ambient_vote(bid, qg, "for", handle_id=h1)
    svc.cast_vote(bid, qg, "for", handle_id=h1)               # explicit supersedes
    svc.retract_vote(bid, qg, handle_id=h1)                   # no-op on explicit
    counted = m.counted(qg, h1)
    assert counted is not None and counted.channel == "explicit"
    assert svc.read_system_log(bid, GOVERNANCE_SETTLED) == []

    svc.record_ambient_vote(bid, qg, "for", handle_id=env.h["Polemarchus"])
    svc.record_ambient_vote(bid, qg, "for", handle_id=env.h["Thrasymachus"])
    assert m.q_status(qg) == ("settled", "for")
    assert len(svc.read_system_log(bid, GOVERNANCE_SETTLED)) == 1


# -- AC3: close freezes, snapshots the tray, ends input --------------------


def test_close_freezes_tallies_snapshots_tray_and_ends_input(tmp_path):
    env = governance_board(tmp_path)
    svc, bid, m = env.service, env.board_id, env.machine
    h = env.h
    ce1, q1 = m.open_refutation_q("n1", "3a", opened_by=h["Cephalus"])
    svc.cast_vote(bid, q1, "stands", handle_id=h["Cephalus"])
    svc.cast_vote(bid, q1, "rebutted", handle_id=h["Polemarchus"])     # 1-1, standing
    ce2, q2 = m.open_refutation_q("n1", "3b", opened_by=h["Thrasymachus"])
    svc.cast_vote(bid, q2, "stands", handle_id=h["Thrasymachus"])      # 1-0, standing
    q3 = svc.propose_ingress_selection(bid, "cand", opened_by=h["Cephalus"])
    assert m.q_status(q3) == ("open", None)

    qc = svc.propose_close(bid, opened_by=h["Cephalus"])
    _vote(svc, env, qc, "for")

    assert m.state.status == "closed"
    assert m.is_closed()
    assert m.q_status(q1) == ("frozen", None)
    assert m.q_status(q2) == ("frozen", None)
    assert m.q_status(q3) == ("frozen", None)
    assert m.state.carried_unresolved == [{
        "node_id": "n1",
        "status": "carried_unresolved",
        "ces": [ce1, ce2],
    }]
    row = _settled_row(svc, bid, qc)
    assert row["outcome"] == "for"
    assert row["tally"] == {"for": 3, "against": 0}
    assert row["census_size"] == 5
    assert row["carried_unresolved"] == m.state.carried_unresolved
    assert row["closed_seq"] == m.state.canvas["closed_seq"]
    assert svc.board(bid).status == "closed"        # registry mirror

    # input ends for every mutator... (fused per approved plan §3.3:
    # force_settle on an already-settled Q is an idempotent read-back that
    # returns its outcome without re-firing; force_settle on a frozen/open Q
    # still raises BoardClosed as terminal input.)
    with pytest.raises(BoardClosed):
        svc.cast_vote(bid, q3, "for", handle_id=h["Cephalus"])
    with pytest.raises(BoardClosed):
        svc.retract_vote(bid, q3, handle_id=h["Cephalus"])
    assert svc.force_settle(bid, qc) == "for"
    with pytest.raises(BoardClosed):
        svc.force_settle(bid, q3)
    with pytest.raises(BoardClosed):
        svc.propose_close(bid, opened_by=h["Cephalus"])
    with pytest.raises(BoardClosed):
        svc.propose_mode_switch(bid, "facilitates", opened_by=h["Cephalus"])
    with pytest.raises(BoardClosed):
        svc.propose_socrates_swap(bid, h["Polemarchus"],
                                  opened_by=h["Cephalus"])
    with pytest.raises(BoardClosed):
        svc.propose_active_claim_switch(bid, "n1", opened_by=h["Cephalus"])
    with pytest.raises(BoardClosed):
        svc.propose_ingress_selection(bid, "cand", opened_by=h["Cephalus"])
    with pytest.raises(BoardClosed):
        svc.claim_original(bid, "no more claims", claimant_display="Cephalus")
    with pytest.raises(BoardClosed):
        svc.revise(bid, "no more revisions", claimant_display="Cephalus")

    # ...but every read still works, frozen tallies included
    assert svc.view(bid)["status"] == "closed"
    assert svc.read_system_log(bid)
    assert svc.read_events(bid)
    status = svc.governance_status(bid, q3)
    assert status["status"] == "frozen"
    assert status["tally"] == {"for": 0, "against": 0}


def test_rejected_close_changes_nothing(tmp_path):
    env = governance_board(tmp_path)
    svc, bid, m = env.service, env.board_id, env.machine
    q = svc.propose_close(bid, opened_by=env.h["Cephalus"])
    _vote(svc, env, q, "against")
    assert m.q_status(q) == ("settled", "against")
    assert not m.is_closed()
    assert m.state.carried_unresolved is None
    assert not [e for e in m.events if e["type"] == "board_closed"]
    row = _settled_row(svc, bid, q)
    assert row["outcome"] == "against"
    assert "carried_unresolved" not in row

    # the room is still live and the close slot is free again
    q2 = svc.propose_ingress_selection(bid, "cand", opened_by=env.h["Cephalus"])
    svc.cast_vote(bid, q2, "for", handle_id=env.h["Cephalus"])
    assert m.counted(q2, env.h["Cephalus"]) is not None
    again = svc.propose_close(bid, opened_by=env.h["Cephalus"])
    assert m.q_status(again) == ("open", None)


def test_close_settlement_is_idempotent(tmp_path):
    env = governance_board(tmp_path)
    svc, bid, m = env.service, env.board_id, env.machine
    qc = svc.propose_close(bid, opened_by=env.h["Cephalus"])
    _vote(svc, env, qc, "for")
    assert m.is_closed()
    assert len([e for e in m.events if e["type"] == "board_closed"]) == 1

    # machine fix: a second close_board on the terminal board is a no-op
    assert m.close_board(qc) is None
    assert len([e for e in m.events if e["type"] == "board_closed"]) == 1
    # fused per approved plan §3.3: re-settling the settled close Q is an
    # idempotent read-back (returns "for"), never a second board_closed.
    assert svc.force_settle(bid, qc) == "for"
    assert len([e for e in svc.read_system_log(bid, GOVERNANCE_SETTLED)
                if e["payload"]["q_id"] == qc]) == 1

    # read-based dedupe is reload-proof (no in-memory settled set)
    reopened = make_service(tmp_path)
    assert reopened.board(bid).status == "closed"
    assert len([e for e in reopened.read_system_log(bid, GOVERNANCE_SETTLED)
                if e["payload"]["q_id"] == qc]) == 1
