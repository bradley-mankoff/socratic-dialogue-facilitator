"""AC2 — CE census freezes at Q open; late casters are included; late
non-voters never enter; facilitator membership follows mode."""


def test_open_roster_frozen_late_nonvoter_never_enters(make_env):
    env = make_env(humans=("a", "b", "c"))
    m, q = env.machine, env.q
    d = m.enroll_handle("d")          # enrolled after Q open
    assert d not in m.census(q)       # and never casts
    m.cast(q, env.h["a"], "explicit", "stands")
    m.cast(q, env.h["b"], "explicit", "stands")
    # census stays {a,b,c}: d absent keeps the denominator at 3 → refuted
    assert m.census(q) == frozenset(env.h[n] for n in ("a", "b", "c"))
    assert m.is_refuted(env.ce) is True


def test_late_caster_joins_census_and_can_unrefute(make_env):
    env = make_env(humans=("a", "b", "c"))
    m, q = env.machine, env.q
    d = m.enroll_handle("d")
    m.cast(q, env.h["a"], "explicit", "stands")
    m.cast(q, env.h["b"], "explicit", "stands")
    m.cast(q, env.h["c"], "explicit", "rebutted")
    assert m.is_refuted(env.ce) is True           # 2/1 over census 3
    m.cast(q, d, "explicit", "rebutted")          # late caster joins
    assert d in m.census(q)
    assert m.census(q) == frozenset(env.h[n] for n in ("a", "b", "c")) | {d}
    # 2/2 over census 4 → 2*2 == 4 un-refutes
    assert m.is_refuted(env.ce) is False
    flips = [e["payload"] for e in m.events
             if e["type"] == "node_status_changed"]
    assert flips[-1] == {"node_id": env.node, "status": "unrefuted"}


def test_unrelated_q_activity_never_pollutes_census(make_env):
    env = make_env(humans=("a", "b", "c"))
    m, q = env.machine, env.q
    m.cast(q, env.h["a"], "explicit", "stands")
    m.cast(q, env.h["b"], "explicit", "stands")
    before = m.census(q)
    # second CE on the same node with its own Q
    ce2, q2 = m.open_refutation_q(env.node, "3b", opened_by=env.h["c"])
    assert q2 != q
    m.cast(q2, env.h["c"], "explicit", "stands")
    m.cast(q2, env.h["a"], "explicit", "rebutted")
    assert m.census(q) == before
    assert m.census(q) == frozenset(env.h[n] for n in ("a", "b", "c"))


def test_facilitator_in_census_only_in_participates(make_env):
    env = make_env(humans=("a", "b"), mode="participates", facilitator=True)
    m, q = env.machine, env.q
    # participates: facilitator is in the open roster
    assert env.f in m.census(q)
    m.cast(q, env.h["a"], "explicit", "stands")
    m.cast(q, env.h["b"], "explicit", "rebutted")
    m.cast(q, env.f, "explicit", "stands")
    assert env.f in m.census(q)

    env2 = make_env(humans=("a", "b"), mode="facilitates", facilitator=True)
    m2, q2 = env2.machine, env2.q
    assert env2.f not in m2.census(q2)
    m2.cast(q2, env2.h["a"], "explicit", "stands")
    assert env2.f not in m2.census(q2)


def test_ambient_only_caster_enters_census_exactly_once(make_env):
    env = make_env(humans=("a", "b", "c"))
    m, q = env.machine, env.q
    m.record_ambient(q, env.h["c"], "stands", receive_time=1.0)
    census = m.census(q)
    assert env.h["c"] in census           # joins via its counted ballot
    assert census == frozenset(env.h[n] for n in ("a", "b", "c"))
    # a set — counted exactly once no matter how many ambient casts
    m.record_ambient(q, env.h["c"], "rebutted", receive_time=2.0)
    assert m.census(q) == frozenset(env.h[n] for n in ("a", "b", "c"))