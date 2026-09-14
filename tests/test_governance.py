"""Governance Qs: strict-majority settlement, no timeouts, 1-human
exemption, ties fail, and the Facilitates-mode tiebreak protocol."""

import pytest

from board.machine import (
    DuplicateTiebreak,
    TiebreakNotPassed,
    VerdictError,
)


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


def test_one_human_exemption_on_governance_q(make_env):
    env = make_env(humans=("human",), mode="participates", facilitator=True)
    m = env.machine
    q = m.open_governance_q("ingress_selection", subject="candidate-x",
                            opened_by=env.h["human"])
    m.cast(q, env.h["human"], "explicit", "for")
    m.cast(q, env.f, "explicit", "against")
    # true tie 1–1; the single human's ballot is decisive → "for" wins
    assert m.governance_passed(q) == "for"
    assert m.q_status(q) == ("settled", "for")


def test_tiebreak_requires_facilitates_and_once_per_ce(make_env):
    env = make_env(humans=("a", "b"), mode="facilitates", facilitator=True)
    m = env.machine
    tb = m.open_governance_q("tiebreak", subject=env.ce, opened_by=env.h["a"])
    assert m.state.ces[env.ce].tiebreak_invoked is True
    with pytest.raises(DuplicateTiebreak):
        m.open_governance_q("tiebreak", subject=env.ce, opened_by=env.h["a"])

    # participates mode refuses tiebreak invocation entirely
    env2 = make_env(humans=("a", "b"), mode="participates", facilitator=True)
    with pytest.raises(VerdictError):
        env2.machine.open_governance_q("tiebreak", subject=env2.ce,
                                       opened_by=env2.h["a"])


def test_tiebreak_ballot_only_after_passed_invoke(make_env):
    env = make_env(humans=("a", "b"), mode="facilitates", facilitator=True)
    m = env.machine
    m.open_governance_q("tiebreak", subject=env.ce, opened_by=env.h["a"])
    with pytest.raises(TiebreakNotPassed):
        m.tiebreak_ballot(env.ce, "not yet empowered")


def test_tiebreak_passed_flow(make_env):
    env = make_env(humans=("a", "b", "c"), mode="facilitates",
                   facilitator=True)
    m, q = env.machine, env.q
    # 1–1 human tie on the CE's refutation Q (census {a,b,c})
    m.cast(q, env.h["a"], "explicit", "stands")
    m.cast(q, env.h["b"], "explicit", "rebutted")
    assert m.is_standing(env.ce) is True
    assert m.is_refuted(env.ce) is False

    tb = m.open_governance_q("tiebreak", subject=env.ce, opened_by=env.h["a"])
    m.cast(tb, env.h["a"], "explicit", "for")
    m.cast(tb, env.h["b"], "explicit", "for")
    assert m.q_status(tb) == ("settled", "for")

    ballot = m.tiebreak_ballot(env.ce, "the example misapplies the term")
    b = m.counted(q, env.f)
    assert b is not None
    assert b.ballot_id == ballot
    assert b.labeled is True
    assert b.side == "rebutted"
    assert b.channel == "explicit"
    assert b.reason == "the example misapplies the term"
    assert m.state.ces[env.ce].tiebreak_ballot_id == ballot

    # the labeled tiebreak ballot counts in the tally but takes no census
    # seat (facilitator is not a franchise holder in facilitates mode)
    assert env.f not in m.census(q)
    assert m.standing_counts(env.ce) == (1, 2)
    assert m.is_standing(env.ce) is False    # rebutted → not standing
    assert m.is_refuted(env.ce) is False     # still-not-refuted stays so

    # exactly one labeled reasoned ballot; no second ballot, no second invoke
    with pytest.raises(DuplicateTiebreak):
        m.tiebreak_ballot(env.ce, "once more")
    with pytest.raises(DuplicateTiebreak):
        m.open_governance_q("tiebreak", subject=env.ce, opened_by=env.h["a"])


def test_tiebreak_missing_reason_refused(make_env):
    env = make_env(humans=("a", "b", "c"), mode="facilitates",
                   facilitator=True)
    m = env.machine
    tb = m.open_governance_q("tiebreak", subject=env.ce, opened_by=env.h["a"])
    m.cast(tb, env.h["a"], "explicit", "for")
    m.cast(tb, env.h["b"], "explicit", "for")
    with pytest.raises(ValueError):
        m.tiebreak_ballot(env.ce, "")
    with pytest.raises(ValueError):
        m.tiebreak_ballot(env.ce, None)
    assert m.state.ces[env.ce].tiebreak_ballot_id is None


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