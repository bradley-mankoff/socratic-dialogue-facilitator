"""AC3a — mode-switch recompute (withdrawal of facilitator ballots on open
refutation Qs only) and medium toggle (zero predicate effect)."""

import pytest

from board.machine import (
    FacilitatorCannotVote,
    ModeSwitchNotSettled,
)


def _open_mode_switch(m, opened_by, new_mode):
    return m.open_governance_q("mode_switch", subject=new_mode,
                               opened_by=opened_by)


def test_switch_mode_refuses_unsettled_q(make_env):
    env = make_env(humans=("a", "b", "c"), mode="participates",
                   facilitator=True)
    m = env.machine
    q = _open_mode_switch(m, env.h["a"], "facilitates")
    with pytest.raises(ModeSwitchNotSettled):
        m.switch_mode(q, "facilitates")
    with pytest.raises(ModeSwitchNotSettled):
        m.switch_mode(env.q, "facilitates")     # refutation Q is not a switch


def test_participates_to_facilitates_withdraws_and_flips(make_env):
    env = make_env(humans=("a", "b", "c"), mode="participates",
                   facilitator=True)
    m, q = env.machine, env.q
    m.cast(q, env.h["a"], "explicit", "stands")
    m.cast(q, env.h["b"], "explicit", "rebutted")
    m.cast(q, env.f, "explicit", "stands")
    # census 4 (facilitator is in the participates roster): 2/2 tie
    assert env.f in m.census(q)
    assert m.is_standing(env.ce) is True
    assert m.is_refuted(env.ce) is False

    q2 = _open_mode_switch(m, env.h["a"], "facilitates")
    for who in ("a", "b", "c"):
        m.cast(q2, env.h[who], "explicit", "for")
    assert m.q_status(q2) == ("settled", "for")
    assert m.state.mode == "facilitates"

    # facilitator's open-Q ballot withdrawn; census drops the facilitator;
    # the standing verdict flips because it depended on the facilitator
    assert m.counted(q, env.f) is None
    assert env.f not in m.census(q)
    assert m.standing_counts(env.ce) == (1, 1)
    assert m.is_refuted(env.ce) is False
    with pytest.raises(FacilitatorCannotVote):
        m.cast(q, env.f, "explicit", "stands")

    applied = [e for e in m.events if e["type"] == "mode_switch_applied"]
    assert applied[-1]["payload"]["mode"] == "facilitates"
    assert set(applied[-1]["payload"]["withdrawn_ballot_ids"])


def test_settled_q_untouched_by_mode_switch(make_env):
    env = make_env(humans=("a", "b", "c"), mode="participates",
                   facilitator=True)
    m = env.machine
    gi = m.open_governance_q("ingress_selection", subject="candidate-x",
                             opened_by=env.h["a"])
    for who in ("a", "b", "c"):
        m.cast(gi, env.h[who], "explicit", "for")
    assert m.q_status(gi) == ("settled", "for")

    q2 = _open_mode_switch(m, env.h["a"], "facilitates")
    for who in ("a", "b", "c"):
        m.cast(q2, env.h[who], "explicit", "for")
    assert m.state.mode == "facilitates"
    # settled governance Q's outcome is history — untouched by the switch
    assert m.q_status(gi) == ("settled", "for")


def test_facilitates_to_participates_reelegible_no_retroactive(make_env):
    env = make_env(humans=("a", "b"), mode="participates", facilitator=True)
    m, q = env.machine, env.q
    m.cast(q, env.h["a"], "explicit", "stands")
    m.cast(q, env.f, "explicit", "stands")

    q2 = _open_mode_switch(m, env.h["a"], "facilitates")
    m.cast(q2, env.h["a"], "explicit", "for")
    m.cast(q2, env.h["b"], "explicit", "for")
    assert m.state.mode == "facilitates"
    assert m.counted(q, env.f) is None

    q3 = _open_mode_switch(m, env.h["a"], "participates")
    m.cast(q3, env.h["a"], "explicit", "for")
    m.cast(q3, env.h["b"], "explicit", "for")
    assert m.state.mode == "participates"
    # re-eligible: new ballot counts, old withdrawn ballot stays withdrawn
    bid = m.cast(q, env.f, "explicit", "stands")
    assert m.counted(q, env.f).ballot_id == bid
    assert m.standing_counts(env.ce) == (2, 0)     # no retroactive ballot
    # facilitator rejoined via its new ballot, not the roster
    assert env.f in m.census(q)


def test_medium_toggle_changes_only_the_field(make_env):
    env = make_env(humans=("a", "b", "c"))
    m, q = env.machine, env.q
    m.cast(q, env.h["a"], "explicit", "stands")
    m.cast(q, env.h["b"], "explicit", "stands")
    m.cast(q, env.h["c"], "explicit", "rebutted")
    ticks = m.toggle_medium("live")
    assert ticks is None
    assert m.state.medium == "live"
    before = m.snapshot()
    before.pop("medium", None)
    after = m.snapshot()
    after.pop("medium", None)
    assert before == after                      # whole-snapshot diff
    assert m.census(q) == frozenset(env.h[n] for n in ("a", "b", "c"))
    assert m.is_refuted(env.ce) is True


def test_async_stays_open_and_live_same_predicate(make_env):
    env = make_env(humans=("a", "b", "c"))
    m, q = env.machine, env.q
    m.cast(q, env.h["a"], "explicit", "stands")
    m.cast(q, env.h["b"], "explicit", "rebutted")
    assert m.q_status(q)[0] == "open"           # 1–1 census 3, undecided
    m.enroll_handle("d")                        # unrelated mutations
    m.toggle_medium("live")
    ce2, q2 = m.open_refutation_q(env.node, "3b", opened_by=env.h["c"])
    m.cast(q2, env.h["c"], "explicit", "stands")
    # same predicate over the same census in live mode
    assert m.census(q) == frozenset(env.h[n] for n in ("a", "b", "c"))
    assert m.is_standing(env.ce) is True
    assert m.q_status(q)[0] == "open"
    m.cast(q, env.h["c"], "explicit", "rebutted")
    assert m.q_status(q)[0] == "open"