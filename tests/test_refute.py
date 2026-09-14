"""AC1 — integer refute predicate: strict census majority, ties fail,
halves/shortfalls fail, 1-human exception, re-vote on the active node,
inactive-node freeze."""

import pytest

from board.machine import NodeFrozen
from board.verdicts import tie_exemption_handle


def test_strict_majority_refutes(make_env):
    env = make_env(humans=("a", "b", "c"))
    m, q = env.machine, env.q
    assert m.q_status(q)[0] == "open"
    m.cast(q, env.h["a"], "explicit", "stands")
    m.cast(q, env.h["b"], "explicit", "stands")
    m.cast(q, env.h["c"], "explicit", "rebutted")
    # census 3, 2 stands / 1 rebutted → strict majority
    assert m.census(q) == frozenset(env.h[n] for n in ("a", "b", "c"))
    assert m.is_standing(env.ce)
    assert m.is_refuted(env.ce) is True
    assert m.node_is_refuted(env.node)
    # refutation Qs never settle on majority — they stay open for re-votes
    assert m.q_status(q)[0] == "open"


def test_tie_fails(make_env):
    env = make_env(humans=("a", "b", "c", "d"))
    m, q = env.machine, env.q
    m.cast(q, env.h["a"], "explicit", "stands")
    m.cast(q, env.h["b"], "explicit", "stands")
    m.cast(q, env.h["c"], "explicit", "rebutted")
    m.cast(q, env.h["d"], "explicit", "rebutted")
    # census 4, 2/2: standing holds (CE is not defeated) but refutation
    # needs 2*stands > census — 4 > 4 fails.
    assert m.is_standing(env.ce) is True
    assert m.is_refuted(env.ce) is False


def test_halve_fails(make_env):
    env = make_env(humans=("a", "b", "c", "d"))
    m, q = env.machine, env.q
    m.cast(q, env.h["a"], "explicit", "stands")
    m.cast(q, env.h["b"], "explicit", "stands")
    # 2*2 == 4 → halve fails
    assert m.is_standing(env.ce) is True
    assert m.is_refuted(env.ce) is False


def test_shortfall_fails(make_env):
    env = make_env(humans=("a", "b", "c", "d", "e", "f"))
    m, q = env.machine, env.q
    m.cast(q, env.h["a"], "explicit", "stands")
    m.cast(q, env.h["b"], "explicit", "stands")
    m.cast(q, env.h["c"], "explicit", "stands")
    m.cast(q, env.h["d"], "explicit", "rebutted")
    m.cast(q, env.h["e"], "explicit", "rebutted")
    # census 6, 3 stands / 2 rebutted: 2*3 == 6 → not > 6, shortfall fails
    assert m.is_standing(env.ce) is True
    assert m.is_refuted(env.ce) is False


def test_zero_zero_not_standing(make_env):
    env = make_env()
    assert not m_is_standing(env)
    assert not engine_is_refuted(env)


def m_is_standing(env):
    return env.machine.is_standing(env.ce)


def engine_is_refuted(env):
    return env.machine.is_refuted(env.ce)


def test_standing_but_not_refuted(make_env):
    env = make_env(humans=("a", "b", "c", "d", "e", "f"))
    m, q = env.machine, env.q
    m.cast(q, env.h["a"], "explicit", "stands")
    m.cast(q, env.h["b"], "explicit", "stands")
    m.cast(q, env.h["c"], "explicit", "stands")
    m.cast(q, env.h["d"], "explicit", "rebutted")
    # census 6, 3/1: standing True, 2*3 == 6 not > 6 → not refuted
    assert m.is_standing(env.ce) is True
    assert m.is_refuted(env.ce) is False


def test_one_human_exception_decisive_on_tie(make_env):
    env = make_env(humans=("human",), mode="participates", facilitator=True)
    m, q = env.machine, env.q
    m.cast(q, env.h["human"], "explicit", "stands")
    m.cast(q, env.f, "explicit", "rebutted")
    # census {human, facilitator} = 2, 1–1 true tie; the single human's
    # ballot is decisive → stands wins → the CE refutes.
    assert tie_exemption_handle(m.state, q) == env.h["human"]
    assert m.is_standing(env.ce) is True
    assert m.is_refuted(env.ce) is True


def test_one_human_exception_rebutted_side(make_env):
    env = make_env(humans=("human",), mode="participates", facilitator=True)
    m, q = env.machine, env.q
    m.cast(q, env.h["human"], "explicit", "rebutted")
    m.cast(q, env.f, "explicit", "stands")
    assert tie_exemption_handle(m.state, q) == env.h["human"]
    # the human's word settles: rebutted → CE does not stand, not refuted
    assert m.is_standing(env.ce) is False
    assert m.is_refuted(env.ce) is False


def test_two_human_tie_stays_fails(make_env):
    env = make_env(humans=("a", "b"), mode="participates", facilitator=True)
    m, q = env.machine, env.q
    m.cast(q, env.h["a"], "explicit", "stands")
    m.cast(q, env.h["b"], "explicit", "rebutted")
    # two humans → no exemption; 1–1 tie census 2 (facilitator abstains)
    assert tie_exemption_handle(m.state, q) is None
    assert m.is_refuted(env.ce) is False
    assert m.q_status(q)[0] == "open"


def test_revote_refutes_then_unrefutes_active_node(make_env):
    env = make_env(humans=("a", "b", "c"))
    m, q = env.machine, env.q
    m.cast(q, env.h["a"], "explicit", "stands")
    m.cast(q, env.h["b"], "explicit", "stands")
    m.cast(q, env.h["c"], "explicit", "rebutted")
    assert m.is_refuted(env.ce) is True
    assert m.node_is_refuted(env.node) is True
    # re-vote: latest counts both ways — b flips to rebutted
    m.cast(q, env.h["b"], "explicit", "rebutted")
    assert m.is_refuted(env.ce) is False
    statuses = [e["payload"]["status"] for e in m.events
                if e["type"] == "node_status_changed"]
    assert statuses[-2:] == ["refuted", "unrefuted"]


def test_inactive_node_revote_refused_and_frozen(make_env):
    env = make_env(humans=("a", "b", "c"))
    m, q = env.machine, env.q
    m.cast(q, env.h["a"], "explicit", "stands")
    m.cast(q, env.h["b"], "explicit", "stands")
    m.cast(q, env.h["c"], "explicit", "rebutted")
    assert m.is_refuted(env.ce) is True
    n2 = m.register_node("n2", "Justice is the interest of the stronger.")
    assert m.state.nodes[env.node].is_active is False
    assert m.q_status(q)[0] == "frozen"
    # re-vote on the inactive node is refused, not silently ignored
    with pytest.raises(NodeFrozen):
        m.cast(q, env.h["a"], "explicit", "rebutted")
    # frozen verdict unchanged
    assert m.is_refuted(env.ce) is True
    assert m.node_is_refuted(env.node) is True
    assert m.state.active_node_id == n2