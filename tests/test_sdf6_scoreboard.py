"""AC4 — the live scoreboard shows who voted what.

Story 19: every ballot renders with its display and counted-ness, numbers
match the machine's reads exactly, and the whole shape survives a JSON
round-trip.
"""

import json

import pytest

from board.machine import UnknownNode
from server.errors import NoActiveClaim
from tests.sdf6_stubs import make_svc


def test_scoreboard_who_voted_what(tmp_path):
    env = make_svc(tmp_path)
    service, bid, machine = env.service, env.board_id, env.machine
    service.record_ambient_vote(bid, env.q, "stands", by_display="Cephalus",
                                receive_time=1.0)
    service.cast_vote(bid, env.q, "rebutted", by_display="Cephalus",
                      receive_time=2.0, reason="heard Socrates on it")
    service.record_ambient_vote(bid, env.q, "stands", by_display="Polemarchus",
                                receive_time=1.0)

    sb = service.scoreboard(bid)
    assert sb["board_id"] == bid
    assert sb["node_id"] == sb["claim_id"] == env.node
    row = sb["ces"][0]
    assert row["ce_id"] == env.ce and row["shape"] == "3a"
    votes = row["votes"]
    # every ballot listed, oldest first by (receive_time, seq)
    order = [(v["receive_time"], v["seq"]) for v in votes]
    assert order == sorted(order)
    assert [v["display"] for v in votes] == [
        "Cephalus", "Polemarchus", "Cephalus"]
    assert [v["channel"] for v in votes] == ["ambient", "ambient", "explicit"]
    assert [v["is_counted"] for v in votes] == [False, True, True]
    assert [v["side"] for v in votes] == ["stands", "stands", "rebutted"]
    # exactly one counted ballot per handle; explicit precedence visible
    counted_per_handle = {}
    for v in votes:
        counted_per_handle.setdefault(v["handle_id"], 0)
        counted_per_handle[v["handle_id"]] += 1 if v["is_counted"] else 0
    assert counted_per_handle == {h: 1 for h in
                                  (env.h["Cephalus"], env.h["Polemarchus"])}
    # the counted explicit row carries its reason
    assert votes[2]["reason"] == "heard Socrates on it"
    assert votes[0]["reason"] is None


def sb_is_refuted(service, bid):
    return service.scoreboard(bid)["is_refuted"]


def test_scoreboard_numbers_match_machine(tmp_path):
    env = make_svc(tmp_path)
    service, bid, machine = env.service, env.board_id, env.machine
    import board.verdicts as V
    service.cast_vote(bid, env.q, "stands", by_display="Cephalus")
    service.record_ambient_vote(bid, env.q, "stands", by_display="Cephalus",
                                receive_time=5.0)
    service.cast_vote(bid, env.q, "rebutted", by_display="Polemarchus")
    fresh = service.allege(bid, "3b", by_display="Thrasymachus")
    ce2, q2 = fresh.ce_id, fresh.q_id
    service.cast_vote(bid, q2, "rebutted", by_display="Polemarchus")
    service.cast_vote(bid, q2, "rebutted", by_display="Cephalus")

    sb = service.scoreboard(bid)
    state = machine.state
    assert sb["is_refuted"] == machine.is_refuted(env.node)
    assert sb["node_status"] == machine.state.nodes[env.node].status
    assert [row["ce_id"] for row in sb["ces"]] == [env.ce, ce2]
    for row, ce in zip(sb["ces"], (env.ce, ce2)):
        stands, rebutted = machine.standing_counts(ce)
        assert row["tally"] == {"stands": stands, "rebutted": rebutted}
        assert row["census_size"] == len(machine.census(row["q_id"]))
        assert row["is_standing"] == machine.is_standing(ce)
        assert row["is_refuted"] == V.ce_is_refuted(state, ce)
        assert row["outcome"] == V.refutation_outcome(state, ce)
        assert row["q_status"] == state.questions[row["q_id"]].status
    # and the header is the machine's node-level verdict, not a re-derivation
    assert sb["is_refuted"] is False
    assert machine.state.nodes[env.node].status == "unrefuted"
    assert sb["node_status"] == "unrefuted"
    del q2


def test_scoreboard_json_and_scoping(tmp_path):
    env = make_svc(tmp_path)
    service, bid, machine = env.service, env.board_id, env.machine
    service.cast_vote(bid, env.q, "stands", by_display="Cephalus")
    sb = service.scoreboard(bid)
    assert json.loads(json.dumps(sb)) == sb

    # default scope is the active claim; explicit node_id wins
    assert service.scoreboard(bid) == service.scoreboard(bid, env.node)
    fresh = service.allege(bid, "3b")
    ce2 = fresh.ce_id
    assert service.scoreboard(bid, env.node)["ces"][0]["ce_id"] == env.ce
    assert service.scoreboard(bid, env.node)["ces"][1]["ce_id"] == ce2

    from board.machine import UnknownNode
    with pytest.raises(UnknownNode):
        service.scoreboard(bid, "nX")
    # a claimless board cannot be scored
    bare = make_svc(tmp_path / "bare", allege=False, claim=False)
    with pytest.raises(NoActiveClaim):
        bare.service.scoreboard(bare.board_id)
    # a claim with no counterexamples scores clean
    plain = make_svc(tmp_path / "plain", allege=False)
    empty = plain.service.scoreboard(plain.board_id)
    assert empty["ces"] == []
    assert empty["is_refuted"] is False
    assert empty["node_status"] == "open"


def test_scoreboard_shows_withdrawn_rows(tmp_path):
    env = make_svc(tmp_path)
    service, bid, machine = env.service, env.board_id, env.machine
    first = service.record_ambient_vote(bid, env.q, "stands",
                                        by_display="Cephalus",
                                        receive_time=1.0)
    second = service.record_ambient_vote(bid, env.q, "rebutted",
                                         by_display="Cephalus",
                                         receive_time=2.0)
    service.retract_vote(bid, env.q, handle_id=env.h["Cephalus"])
    row = service.scoreboard(bid)["ces"][0]
    by_id = {v["ballot_id"]: v for v in row["votes"]}
    withdrawn = by_id[second.ballot_id]
    assert withdrawn["withdrawn"] is True
    assert withdrawn["is_counted"] is False
    resurfaced = by_id[first.ballot_id]
    assert resurfaced["withdrawn"] is False
    assert resurfaced["is_counted"] is True
    # tallies stay consistent with the machine: the older ambient counts
    stands, rebutted = machine.standing_counts(env.ce)
    assert row["tally"] == {"stands": stands, "rebutted": rebutted}
    assert (stands, rebutted) == (1, 0)
