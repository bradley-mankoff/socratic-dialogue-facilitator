"""Play mode toggle has zero predicate effect (kept from AC3a).

The sdf-zj6.1 cut removed the facilitator participates/facilitates modes
but kept the async/live play-mode toggle. Switching it changes only the
``medium`` field: census, standing and refutation read back the same.
"""

from board.machine import VerdictMachine  # noqa: F401  (suite imports by convention)


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
