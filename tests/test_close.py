"""AC3b — close freeze: one settled close Q fires board_closed; every open
Q freezes; tray + canvas snapshots; terminality survives reload."""

import pytest

from board.machine import BoardClosed, FacilitatorNeverProposes
from board.store import JsonlStore


def test_facilitator_never_proposes_close(make_env):
    env = make_env(humans=("a", "b"), mode="participates", facilitator=True)
    with pytest.raises(FacilitatorNeverProposes):
        env.machine.open_governance_q("close", opened_by=env.f)


def _close_by_vote(m, opened_by, voters):
    qc = m.open_governance_q("close", opened_by=opened_by)
    for who in voters:
        m.cast(qc, who, "explicit", "for")
    return qc


def test_close_freezes_open_tallies_and_is_terminal(make_env):
    env = make_env(humans=("a", "b", "c"))
    m, q = env.machine, env.q
    m.cast(q, env.h["a"], "explicit", "stands")
    m.cast(q, env.h["b"], "explicit", "rebutted")   # open, 1–1 census 3
    _close_by_vote(m, env.h["a"], [env.h["a"], env.h["b"]])
    assert m.is_closed()
    assert m.q_status(q)[0] == "frozen"             # open Q frozen
    assert m.state.status == "closed"
    with pytest.raises(BoardClosed):
        m.cast(q, env.h["a"], "explicit", "stands")
    with pytest.raises(BoardClosed):
        m.enroll_handle("late")
    with pytest.raises(BoardClosed):
        m.register_node("n2", "a new claim")
    with pytest.raises(BoardClosed):
        m.open_refutation_q(env.node, "3b", opened_by=env.h["a"])
    with pytest.raises(BoardClosed):
        m.open_governance_q("ingress_selection", subject="x",
                            opened_by=env.h["a"])
    with pytest.raises(BoardClosed):
        m.toggle_medium("live")
    with pytest.raises(BoardClosed):
        m.retract(q, env.h["a"])
    assert len([e for e in m.events if e["type"] == "board_closed"]) == 1


def test_carried_unresolved_and_canvas_snapshot(make_env):
    env = make_env(humans=("a", "b"))
    m, q = env.machine, env.q
    m.cast(q, env.h["a"], "explicit", "stands")
    m.cast(q, env.h["b"], "explicit", "rebutted")   # 1–1: standing, unresolved
    ce2, q2 = m.open_refutation_q(env.node, "3b", opened_by=env.h["b"])
    m.cast(q2, env.h["a"], "explicit", "stands")    # 1–0: standing, unresolved
    _close_by_vote(m, env.h["a"], [env.h["a"], env.h["b"]])
    assert m.state.nodes[env.node].status == "carried_unresolved"
    assert m.state.carried_unresolved == [{
        "node_id": env.node,
        "status": "carried_unresolved",
        "ces": [env.ce, ce2],
    }]
    canvas = m.state.canvas
    assert canvas is not None
    assert canvas["board_id"] == "board-in-memory"
    assert canvas["status"] == "closed"
    assert canvas["active_node_id"] == env.node
    assert "nodes" in canvas and "ces" in canvas and "questions" in canvas
    assert canvas["carried_unresolved"] == m.state.carried_unresolved


def test_refuted_node_not_carried(make_env):
    env = make_env(humans=("a", "b"))
    m = env.machine
    m.cast(env.q, env.h["a"], "explicit", "stands")
    m.cast(env.q, env.h["b"], "explicit", "stands")     # 2/0 census 2 → refuted
    assert m.is_refuted(env.ce) is True
    _close_by_vote(m, env.h["a"], [env.h["a"], env.h["b"]])
    assert m.state.carried_unresolved == []
    assert m.state.nodes[env.node].status == "refuted"


def test_settled_q_survives_close(make_env):
    env = make_env(humans=("a", "b", "c"))
    m = env.machine
    gi = m.open_governance_q("ingress_selection", subject="candidate-x",
                             opened_by=env.h["a"])
    for who in ("a", "b"):
        m.cast(gi, env.h[who], "explicit", "for")
    assert m.q_status(gi) == ("settled", "for")
    _close_by_vote(m, env.h["a"], [env.h["a"], env.h["b"]])
    assert m.q_status(gi) == ("settled", "for")     # history is frozen, intact


def test_reload_reproduces_closed_state(tmp_path):
    store = JsonlStore(home=tmp_path)
    m = _make_closed_board(store, create=True)
    reopened = _make_closed_board(store, create=False)
    assert reopened.state == m.state
    assert reopened.is_closed()
    with pytest.raises(BoardClosed):
        reopened.enroll_handle("late")


def _make_closed_board(store, create=True):
    from board.machine import VerdictMachine
    m = VerdictMachine(store, "board-close")
    if not create:
        return m
    m.create_board("board-close", "Justice (Republic Book I)",
                   "participates", "async")
    h1 = m.enroll_handle("h1")
    h2 = m.enroll_handle("h2")
    n1 = m.register_node("n1", "Justice is the advantage of the stronger.")
    ce1, q1 = m.open_refutation_q(n1, "3a", opened_by=h1)
    m.cast(q1, h1, "explicit", "stands")
    m.cast(q1, h2, "explicit", "rebutted")
    qc = m.open_governance_q("close", opened_by=h1)
    m.cast(qc, h1, "explicit", "for")
    m.cast(qc, h2, "explicit", "for")
    return m