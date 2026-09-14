"""AC1 front half — ``allege`` opens a labeled CE + its 1:1 refutation Q.

Stories 15–16: shape vocabulary 3a/3b only, target resolution before any
handle enrollment, refusals pass through, and the result is JSON-exact.
"""

import json

import pytest

from board.machine import NodeFrozen
from server.errors import NoActiveClaim, UnknownBoard, UnknownNode
from server.model import AllegationResult
from tests.sdf6_stubs import make_svc


def test_allege_opens_ce_and_q_on_active_claim(tmp_path):
    env = make_svc(tmp_path, allege=False)
    service, bid, machine = env.service, env.board_id, env.machine

    first = service.allege(bid, "3a", by_display="Cephalus")
    assert (first.board_id, first.node_id) == (bid, env.node)
    state = machine.state
    q = state.questions[first.q_id]
    assert q.kind == "refutation"
    assert q.subject == first.ce_id
    assert q.status == "open"
    assert q.opened_by == env.h["Cephalus"]
    assert first.opened_by == env.h["Cephalus"]
    assert first.shape == "3a"
    assert first.opened_seq == q.opened_seq
    # the CE is attached to the active claim, 1:1 with its question
    assert state.ces[first.ce_id].node_id == env.node
    assert state.ces[first.ce_id].q_id == first.q_id
    assert state.ces[first.ce_id].shape == "3a"
    assert state.nodes[env.node].ce_ids == [first.ce_id]

    # a second CE (other shape) on the same claim is legal; ids mint fresh
    second = service.allege(bid, "3b")
    assert second.ce_id != first.ce_id and second.q_id != first.q_id
    assert second.shape == "3b"
    assert second.opened_by is None, "anonymous alleging stays allowed"
    assert state.nodes[env.node].ce_ids == [first.ce_id, second.ce_id]


def test_allege_shape_validation_3a_3b(tmp_path):
    env = make_svc(tmp_path, allege=False)
    service, bid, machine = env.service, env.board_id, env.machine
    before_events = len(service.journals.read_all(bid))
    before_handles = len(machine.state.handles)
    for bad in ("2a", "", None, "3c"):
        with pytest.raises(ValueError):
            service.allege(bid, bad, by_display="Cephalus")
    # nothing journaled, nobody enrolled: validation precedes every write
    assert len(service.journals.read_all(bid)) == before_events
    assert len(machine.state.handles) == before_handles


def test_allege_explicit_node_target_and_refusals(tmp_path):
    env = make_svc(tmp_path, allege=False)
    service, bid = env.service, env.board_id
    # explicit target node works exactly like the default (active) one
    explicit = service.allege(bid, "3a", node_id=env.node,
                              by_display="Cephalus")
    default = service.allege(bid, "3b")
    assert explicit.node_id == default.node_id == env.node

    # a revise supersedes n1: its history is frozen to new allegations
    service.revise(bid, "Justice is teaching what is good.",
                   claimant_display="Thrasymachus",
                   in_response_to=explicit.ce_id)
    with pytest.raises(NodeFrozen):
        service.allege(bid, "3b", node_id=env.node)

    with pytest.raises(UnknownNode):
        service.allege(bid, "3a", node_id="nX")

    # claimless board: nothing to allege against
    bare = make_svc(tmp_path / "bare", allege=False, claim=False)
    with pytest.raises(NoActiveClaim):
        bare.service.allege(bare.board_id, "3a")

    # unknown board is registry-level, before anything else
    with pytest.raises(UnknownBoard):
        service.allege("justice--ghost--999", "3a")


def test_allege_resolves_or_enrolls_display_once(tmp_path):
    env = make_svc(tmp_path, allege=False)
    service, bid, machine = env.service, env.board_id, env.machine
    # known display resolves to the existing handle, never enrolls
    known = service.allege(bid, "3a", by_display="Cephalus")
    assert known.opened_by == env.h["Cephalus"]
    assert len(machine.state.handles) == len(env.h)

    # unknown display enrolls once; a second allege reuses the identity
    first = service.allege(bid, "3b", by_display="Glaucon")
    assert first.opened_by not in env.h.values()
    glaucon = first.opened_by
    again = service.allege(bid, "3a", by_display="Glaucon")
    assert again.opened_by == glaucon
    assert len(machine.state.handles) == len(env.h) + 1

    # handle_id wins when both are given
    both = service.allege(bid, "3b", handle_id=env.h["Polemarchus"],
                          by_display="Cephalus")
    assert both.opened_by == env.h["Polemarchus"]


def test_allege_result_is_json_and_meta_untouched(tmp_path):
    env = make_svc(tmp_path, allege=False)
    service, bid = env.service, env.board_id
    meta_before = len(service.meta.read_events(bid))
    alleged = service.allege(bid, "3a", by_display="Cephalus")
    assert AllegationResult.from_dict(alleged.to_dict()) == alleged
    as_json = json.loads(json.dumps(alleged.to_dict()))
    assert as_json == alleged.to_dict()
    # the sidecar holds claim events only — an allegation never touches it
    assert len(service.meta.read_events(bid)) == meta_before


def test_allege_leaves_registry_mirrors_untouched(tmp_path):
    env = make_svc(tmp_path, allege=False)
    record = env.service.board(env.board_id)
    env.service.allege(env.board_id, "3a", by_display="Cephalus")
    after = env.service.board(env.board_id)
    assert (after.mode, after.medium, after.status) \
        == (record.mode, record.medium, record.status)
