"""Board verdict reads used by views (SDF-6 scoreboard contract)."""

from board import verdicts as V
from board.model import sides_for


def test_counted_dict_matches_counted_ballot(make_env):
    env = make_env(humans=("a", "b"))
    m, q = env.machine, env.q
    m.cast(q, env.h["a"], "explicit", "stands")
    m.record_ambient(q, env.h["b"], "rebutted")
    d = V.counted(m.state, q)
    assert set(d) == {env.h["a"], env.h["b"]}
    assert d[env.h["a"]] == V.counted_ballot(m.state, q, env.h["a"])


def test_sides_for():
    assert sides_for("refutation") == ("stands", "rebutted")
    assert sides_for("close") == ("for", "against")
