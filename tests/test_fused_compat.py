"""Fused a/c compat: panel-c additive APIs under fused (panel-a) semantics.

Panel a is canonical for verdict semantics (ties stand, strict-majority
refute, fixed-rebutted no-seat tiebreak). This file proves the panel-c
helpers fused into this tree behave consistently with those semantics.
"""

from board import verdicts as V
from board.machine import (
    GovernanceNotSettled,
    NodeFrozen,
    NotActiveNode,
    VerdictError,
    VerdictMachine,
    apply_event,
    fold_events,
)
from board.model import GOVERNANCE_KINDS, sides_for
from board.store import JsonlStore


def test_franchise_and_board_census(make_env):
    env = make_env(humans=("a", "b"), facilitator=True)
    m = env.machine
    # participates: facilitator enfranchised
    assert set(V.franchise(m.state)) == {env.h["a"], env.h["b"], env.f}
    assert V.board_census(m.state) == frozenset(V.franchise(m.state))
    assert m.board_census() == V.board_census(m.state)
    # open roster of the refutation Q matches the franchise at open
    assert set(m.state.questions[env.q].open_roster) == set(V.franchise(m.state))


def test_counted_dict_matches_counted_ballot(make_env):
    env = make_env(humans=("a", "b"))
    m, q = env.machine, env.q
    m.cast(q, env.h["a"], "explicit", "stands")
    m.record_ambient(q, env.h["b"], "rebutted")
    d = V.counted(m.state, q)
    assert set(d) == {env.h["a"], env.h["b"]}
    assert d[env.h["a"]] == V.counted_ballot(m.state, q, env.h["a"])
    assert m.counted_all(q) == d


def test_decisive_side_and_tie_exemption_one_human():
    m = VerdictMachine.in_memory()
    h = m.enroll_handle("solo")
    f = m.enroll_handle("facilitator", kind="enrolled", is_facilitator=True)
    n = m.register_node("n1", "claim")
    ce, q = m.open_refutation_q(n, "3a", opened_by=h)
    # solo human stands vs facilitator rebutted -> 1-1 true tie, exemption active
    m.cast(q, h, "explicit", "stands")
    m.cast(q, f, "explicit", "rebutted")
    assert V.tie_exemption_handle(m.state, q) == h
    assert m.tie_exemption(q) == h
    assert V.decisive_side(m.state, q) == "stands"
    assert m.decisive_side(q) == "stands"
    # fused semantics: exemption decides -> standing + refuted
    assert V.is_standing(m.state, ce) is True
    assert V.ce_is_refuted(m.state, ce) is True
    assert m.ce_is_refuted(ce) is True
    assert m.node_is_refuted(n) is True


def test_ce_is_refuted_matches_node_verdict(make_env):
    env = make_env(humans=("a", "b", "c"))
    m, q = env.machine, env.q
    m.cast(q, env.h["a"], "explicit", "stands")
    m.cast(q, env.h["b"], "explicit", "stands")
    m.cast(q, env.h["c"], "explicit", "rebutted")
    assert V.ce_is_refuted(m.state, env.ce) is True
    assert m.ce_is_refuted(env.ce) is True
    assert m.is_refuted(env.ce) is True
    # tie stands but does not refute (fused rule)
    m2env = make_env(humans=("a", "b", "c", "d"))
    m2, q2 = m2env.machine, m2env.q
    m2.cast(q2, m2env.h["a"], "explicit", "stands")
    m2.cast(q2, m2env.h["b"], "explicit", "stands")
    m2.cast(q2, m2env.h["c"], "explicit", "rebutted")
    m2.cast(q2, m2env.h["d"], "explicit", "rebutted")
    assert V.is_standing(m2.state, m2env.ce) is True
    assert V.ce_is_refuted(m2.state, m2env.ce) is False


def test_standing_counts_from_q_and_node_status(make_env):
    env = make_env(humans=("a", "b", "c"))
    m, q = env.machine, env.q
    m.cast(q, env.h["a"], "explicit", "stands")
    m.cast(q, env.h["b"], "explicit", "rebutted")
    assert V.standing_counts_from_q(m.state, q) == (1, 1)
    assert m.standing_counts_from_q(q) == (1, 1)
    assert m.node_status(env.node) == m.state.nodes[env.node].status
    assert m.ce_is_standing(env.ce) == m.is_standing(env.ce)


def test_sides_for_and_governance_kinds():
    assert sides_for("refutation") == ("stands", "rebutted")
    assert sides_for("close") == ("for", "against")
    assert "refutation" not in GOVERNANCE_KINDS
    assert "close" in GOVERNANCE_KINDS


def test_store_helpers_and_machine_open(tmp_path):
    store = JsonlStore(home=tmp_path / "store")
    assert store.FILENAME == "journal.jsonl"
    assert store.board_dir("b9") == store.path_for("b9").parent
    m = VerdictMachine(store=store, board_id="b9")
    m.create_board("b9", "X")
    h = m.enroll_handle("a")
    assert store.journal_lines("b9") == len(store.read_all("b9")) == 2
    reopened = VerdictMachine.open(store, "b9")
    assert reopened.state.to_dict() == m.state.to_dict()
    assert reopened.events == m.events


def test_apply_event_alias_matches_fold():
    m = VerdictMachine.in_memory()
    h = m.enroll_handle("a")
    events = m.events
    state = None
    for e in events:
        state = apply_event(state, e)
    assert state.to_dict() == m.state.to_dict()
    assert fold_events(events).to_dict() == m.state.to_dict()


def test_fused_error_hierarchy():
    assert issubclass(GovernanceNotSettled, VerdictError)
    assert issubclass(NotActiveNode, NodeFrozen)
    assert issubclass(NotActiveNode, VerdictError)
