"""Counted-ballot rules: latest explicit beats older explicit and any
ambient; retraction touches ambient only; one ballot per person;
(receive_time, seq) ordering."""


def test_latest_explicit_beats_older_explicit(make_env):
    env = make_env(humans=("a", "b", "c"))
    m, q = env.machine, env.q
    m.cast(q, env.h["a"], "explicit", "stands", receive_time=1.0)
    m.cast(q, env.h["a"], "explicit", "rebutted", receive_time=2.0)
    assert m.counted(q, env.h["a"]).side == "rebutted"


def test_explicit_beats_ambient_regardless_of_order(make_env):
    env = make_env(humans=("a", "b", "c"))
    m, q = env.machine, env.q
    # ambient received later than explicit still loses
    m.cast(q, env.h["a"], "explicit", "rebutted", receive_time=1.0)
    m.record_ambient(q, env.h["a"], "stands", receive_time=9.0)
    assert m.counted(q, env.h["a"]).side == "rebutted"
    # ambient received earlier than explicit also loses
    m.cast(q, env.h["b"], "explicit", "rebutted", receive_time=9.0)
    m.record_ambient(q, env.h["b"], "stands", receive_time=1.0)
    assert m.counted(q, env.h["b"]).side == "rebutted"


def test_retraction_touches_ambient_only(make_env):
    env = make_env(humans=("a", "b", "c"))
    m, q = env.machine, env.q
    # (i) ambient self-correction: retract falls back to the earlier ambient
    m.cast(q, env.h["a"], "ambient", "stands", receive_time=1.0)
    m.cast(q, env.h["a"], "ambient", "rebutted", receive_time=2.0)
    assert m.counted(q, env.h["a"]).side == "rebutted"
    m.retract(q, env.h["a"])
    assert m.counted(q, env.h["a"]).side == "stands"
    assert m.standing_counts(env.ce) == (1, 0)
    # (ii) explicit ballot cannot be retracted
    b1 = m.cast(q, env.h["b"], "ambient", "stands", receive_time=1.0)
    m.cast(q, env.h["b"], "explicit", "rebutted", receive_time=2.0)
    m.retract(q, env.h["b"])
    assert m.counted(q, env.h["b"]).side == "rebutted"
    assert m.state.ballots[b1].withdrawn is False
    assert m.standing_counts(env.ce) == (1, 1)


def test_one_ballot_per_person_dedup(make_env):
    env = make_env(humans=("a", "b", "c"))
    m, q = env.machine, env.q
    m.record_ambient(q, env.h["a"], "stands", receive_time=1.0)
    m.cast(q, env.h["a"], "explicit", "stands", receive_time=2.0)
    m.record_ambient(q, env.h["b"], "stands", receive_time=1.0)
    # a and b count once each (ambient + explicit dedupe to one ballot)
    assert m.standing_counts(env.ce) == (2, 0)


def test_equal_receive_time_broken_by_seq(make_env):
    env = make_env(humans=("a", "b", "c"))
    m, q = env.machine, env.q
    m.cast(q, env.h["a"], "explicit", "stands", receive_time=5.0)
    m.cast(q, env.h["a"], "explicit", "rebutted", receive_time=5.0)
    assert m.counted(q, env.h["a"]).side == "rebutted"
    assert m.standing_counts(env.ce) == (0, 1)