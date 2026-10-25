"""Governance Qs: strict-majority settlement, no timeouts, the single-handle
exemption, and ties failing."""

import pytest  # noqa: F401  (kept: the suite imports pytest by convention)


def test_gov_q_stays_open_on_tie_and_shortfall(make_env):
    env = make_env(humans=("a", "b", "c", "d"))
    m = env.machine
    q = m.open_governance_q("ingress_selection", subject="candidate-x",
                            opened_by=env.h["a"])
    # tie: 1–1 over census 4
    m.cast(q, env.h["a"], "explicit", "for")
    m.cast(q, env.h["b"], "explicit", "against")
    assert m.q_status(q) == ("open", None)
    # shortfall: 1 for, 0 against over census 4 → 2*1 not > 4
    m.cast(q, env.h["c"], "explicit", "for")
    assert m.q_status(q) == ("open", None)
    # stays open across unrelated mutations — no clock, no timeout
    m.enroll_handle("late")
    m.toggle_medium("live")
    m.open_refutation_q(env.node, "3b", opened_by=env.h["a"])
    assert m.q_status(q) == ("open", None)


def test_gov_q_settles_at_strict_census_majority(make_env):
    env = make_env(humans=("a", "b", "c", "d"))
    m = env.machine
    q = m.open_governance_q("ingress_selection", subject="candidate-x",
                            opened_by=env.h["a"])
    m.cast(q, env.h["a"], "explicit", "for")
    m.cast(q, env.h["b"], "explicit", "for")
    assert m.q_status(q) == ("open", None)         # 2/0 over census 4
    m.cast(q, env.h["c"], "explicit", "for")       # 3/0 → 6 > 4 settles
    assert m.q_status(q) == ("settled", "for")
    assert not m.is_closed()          # ingress_selection effect: recorded only
    settled = [e for e in m.events if e["type"] == "q_settled"]
    assert settled[-1]["payload"]["outcome"] == "for"


def test_single_handle_vote_settles_governance_q(make_env):
    env = make_env(humans=("human",))
    m = env.machine
    q = m.open_governance_q("ingress_selection", subject="candidate-x",
                            opened_by=env.h["human"])
    m.cast(q, env.h["human"], "explicit", "for")
    # census 1: strict majority settles at once
    assert m.governance_passed(q) == "for"
    assert m.q_status(q) == ("settled", "for")


def test_two_handle_tie_fails_on_governance_q(make_env):
    env = make_env(humans=("human", "late"))
    m = env.machine
    q = m.open_governance_q("ingress_selection", subject="candidate-x",
                            opened_by=env.h["human"])
    assert m.census(q) == frozenset({env.h["human"], env.h["late"]})
    m.cast(q, env.h["human"], "explicit", "for")
    m.cast(q, env.h["late"], "explicit", "against")
    # true tie 1–1 over census 2 fails and the question stays open
    assert m.q_status(q) == ("open", None)


def test_settle_force_resolves_governance_not_refutation(make_env):
    env = make_env(humans=("a", "b", "c", "d"))
    m = env.machine
    # refutation Q: settle() reports the current verdict, never settles
    assert m.settle(env.q) is None
    m.cast(env.q, env.h["a"], "explicit", "stands")
    m.cast(env.q, env.h["b"], "explicit", "stands")
    assert m.q_status(env.q)[0] == "open"
    # governance Q: settle() with a majority commits settlement
    q = m.open_governance_q("ingress_selection", subject="candidate-x",
                            opened_by=env.h["a"])
    assert m.settle(q) is None
    m.cast(q, env.h["a"], "explicit", "for")
    m.cast(q, env.h["b"], "explicit", "for")
    assert m.settle(q) is None                       # 2/0 over census 4
    m.cast(q, env.h["c"], "explicit", "for")
    assert m.settle(q) == "for"
    assert m.q_status(q) == ("settled", "for")
