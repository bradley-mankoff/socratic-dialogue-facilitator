"""Fused SDF-6 extras: journal truth + defensive views (panels a+c ideas on b base).

- Panel c proved the journal is the only verdict record: a reopen from disk
  renders the byte-identical scoreboard, and superseded nodes refuse votes.
- Panel a proved views never crash on unknown questions and `replaced`
  is only set when the new ballot actually counts.

These tests pin the fused semantics: b's guarded service + a's
counted-only `replaced` + c's journal-truth reopen.
"""

from __future__ import annotations

import json

import pytest

from board.machine import NodeFrozen, NotActiveNode
from server.views import vote_rows
from tests.sdf5_stubs import fixed_clock, justice_chain, make_service
from tests.sdf6_stubs import make_svc


def test_fused_ballots_on_superseded_node_are_frozen(tmp_path):
    env = make_svc(tmp_path)
    service, bid = env.service, env.board_id
    q = env.q
    service.revise(bid, "Justice is minding your own business.",
                   claimant_display="Cephalus")
    with pytest.raises(NodeFrozen):
        service.cast_vote(bid, q, "stands", by_display="Cephalus")
    with pytest.raises(NodeFrozen):
        service.record_ambient_vote(bid, q, "stands",
                                    by_display="Cephalus")
    # Panel b contract: unknown node -> UnknownNode, superseded history
    # -> NotActiveNode (refused before any handle is enrolled).
    with pytest.raises(NotActiveNode):
        service.allege(bid, "3b", node_id="n1", by_display="Cephalus")
    # history still scores: frozen node renders, active node is clean
    frozen = service.scoreboard(bid, node_id="n1")
    assert frozen["ces"][0]["q_id"] == q
    assert service.scoreboard(bid)["ces"] == []


def test_fused_scoreboard_survives_reopen(tmp_path):
    env = make_svc(tmp_path)
    service, bid = env.service, env.board_id
    service.cast_vote(bid, env.q, "stands", by_display="Cephalus")
    service.cast_vote(bid, env.q, "rebutted", by_display="Polemarchus")
    before = service.scoreboard(bid)
    assert json.loads(json.dumps(before)) == before
    reopened = make_service(tmp_path, chain=justice_chain(),
                            clock=fixed_clock())
    assert reopened.scoreboard(bid) == before
    # vote ledger is journal truth too: same ballots, same counted flags
    assert (reopened.scoreboard(bid)["ces"][0]["votes"]
            == before["ces"][0]["votes"])


def test_fused_vote_rows_unknown_q_renders_empty(tmp_path):
    env = make_svc(tmp_path)
    assert vote_rows(env.machine, "qX") == []


def test_fused_shadowed_ambient_replaces_nothing(tmp_path):
    env = make_svc(tmp_path)
    service, bid = env.service, env.board_id
    ambient = service.record_ambient_vote(bid, env.q, "stands",
                                          by_display="Cephalus")
    explicit = service.cast_vote(bid, env.q, "rebutted",
                                 by_display="Cephalus")
    assert explicit.replaced_ballot_id == ambient.ballot_id
    shadowed = service.record_ambient_vote(bid, env.q, "stands",
                                           by_display="Cephalus")
    assert shadowed.counted is False
    assert shadowed.replaced_ballot_id is None
