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
    UnknownQuestion,
)
from server.errors import (
    GovernanceAlreadyOpen,
    NotAGovernanceQuestion,
)
from server.store import GOVERNANCE_OPENED, GOVERNANCE_SETTLED
from tests.sdf5_stubs import JUSTICE, THRASYMACHUS, make_service

HANDLES = ("Cephalus", "Polemarchus", "Thrasymachus", "Cleitophon")
VOTERS = ("Cephalus", "Polemarchus", "Thrasymachus")


def governance_board(root, *, humans=HANDLES, claim=True):
    """Board on ``root`` with handles enrolled and (optionally) a claim."""
    svc = make_service(root)
    opened = svc.open_board(JUSTICE, pull_canonicals=False)
    board_id = opened.board_id
    machine = svc.machine(board_id)
    h = {name: machine.enroll_handle(name) for name in humans}
    if claim:
        svc.claim_original(board_id, THRASYMACHUS,
                           claimant_display=humans[0])
    return SimpleNamespace(service=svc, board_id=board_id, machine=machine,
                           h=h)


def _vote(svc, env, q_id, side):
    for name in VOTERS:
        svc.cast_vote(env.board_id, q_id, side, handle_id=env.h[name])


def _open_move(svc, env, kind):
    h1 = env.h["Cephalus"]
    if kind == "close":
        return svc.propose_close(env.board_id, opened_by=h1)
    if kind == "ingress_selection":
        return svc.propose_ingress_selection(env.board_id, "candidate-a",
                                             opened_by=h1)
    raise AssertionError(kind)


def _settled_row(svc, board_id, q_id):
    rows = [e["payload"] for e in svc.read_system_log(
        board_id, GOVERNANCE_SETTLED) if e["payload"]["q_id"] == q_id]
    assert len(rows) == 1, f"expected exactly one settled row for {q_id}"
    return rows[0]


# -- AC1: ingress passes by majority and logs as a system event ------------


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


def test_majority_boundaries_and_single_handle(tmp_path):
    env = governance_board(tmp_path / "majority")
    svc, bid, m = env.service, env.board_id, env.machine
    h = env.h
    q = svc.propose_ingress_selection(bid, "cand", opened_by=h["Cephalus"])
    svc.cast_vote(bid, q, "for", handle_id=h["Cephalus"])
    assert m.q_status(q) == ("open", None)          # 1/4
    svc.cast_vote(bid, q, "for", handle_id=h["Polemarchus"])
    assert m.q_status(q) == ("open", None)          # 2/4: 4 not > 4
    assert svc.read_system_log(bid, GOVERNANCE_SETTLED) == []

    svc.cast_vote(bid, q, "for", handle_id=h["Thrasymachus"])
    assert m.q_status(q) == ("settled", "for")      # 3/4: 6 > 4
    assert len(svc.read_system_log(bid, GOVERNANCE_SETTLED)) == 1

    # 1-handle board: the lone handle's vote settles at once (census 1)
    env1 = governance_board(tmp_path / "single", humans=("Solo",))
    svc1, bid1, m1 = env1.service, env1.board_id, env1.machine
    q1 = svc1.propose_ingress_selection(bid1, "cand",
                                        opened_by=env1.h["Solo"])
    svc1.cast_vote(bid1, q1, "for", handle_id=env1.h["Solo"])
    assert m1.q_status(q1) == ("settled", "for")
    assert svc1.read_system_log(bid1, GOVERNANCE_SETTLED)


@pytest.mark.parametrize("kind", ["close", "ingress_selection"])
def test_duplicate_open_refused_per_kind_and_slot_freed(tmp_path, kind):
    env = governance_board(tmp_path)
    svc, m = env.service, env.machine
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
    assert row["census_size"] == 4
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
