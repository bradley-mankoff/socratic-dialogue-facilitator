"""SDF-7 — visible carry tray with press and discard (stories 13, 39).

The half-built slice hands us: revisions emit ``carried_unvoted`` rows and
superseded nodes refuse votes. This file pins the rest:

* revision surfaces attached counterexamples in a visible tray as
  ``carried_unvoted`` (``service.tray`` + ``service.view()["tray"]``);
* press attaches an unvoted tray item to the active node as a new Q;
  discard writes a system-log entry and touches no verdict state;
* tray contents affect neither verdicts nor the canvas live path.

Headless, stubbed chain, no network. Test-first: these fail until the
service grows ``tray`` / ``press_tray_item`` / ``discard_tray_item``.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from board.machine import NodeFrozen
from server.errors import UnknownBoard
from server.model import TRAY_NAME
from server.store import TRAY_DISCARDED, TRAY_PRESSED
from tests.sdf5_stubs import THRASYMACHUS, make_service


def _room(tmp_path):
    """Justice board, three humans, v1 claimed, two CEs under vote."""
    service = make_service(tmp_path)
    opened = service.open_board("Justice")
    bid = opened.board_id
    machine = service.machine(bid)
    h = {d: machine.enroll_handle(d)
         for d in ("Cephalus", "Polemarchus", "Thrasymachus")}
    service.claim_original(bid, THRASYMACHUS, claimant_display="Cephalus")
    ce1, q1 = machine.open_refutation_q("n1", "3a",
                                        opened_by=h["Cephalus"])
    ce2, q2 = machine.open_refutation_q("n1", "3b",
                                        opened_by=h["Polemarchus"])
    # ce1: 2-1 stands (standing, refutes n1); ce2: 1-2 loses (recorded only)
    machine.cast(q1, h["Cephalus"], "explicit", "stands")
    machine.cast(q1, h["Polemarchus"], "explicit", "stands")
    machine.cast(q1, h["Thrasymachus"], "explicit", "rebutted")
    machine.cast(q2, h["Cephalus"], "explicit", "stands")
    machine.cast(q2, h["Polemarchus"], "explicit", "rebutted")
    machine.cast(q2, h["Thrasymachus"], "explicit", "rebutted")
    return SimpleNamespace(service=service, board_id=bid, machine=machine,
                           h=h, ce1=ce1, q1=q1, ce2=ce2, q2=q2)


def _revise(env):
    return env.service.revise(env.board_id, "Justice is reciprocity.",
                              claimant_display="Polemarchus")


# -- AC1: revision surfaces the visible tray as carried_unvoted -------------


def test_revision_surfaces_tray_as_carried_unvoted(tmp_path):
    env = _room(tmp_path)
    _revise(env)
    tray = env.service.tray(env.board_id)
    assert tray["board_id"] == env.board_id
    assert tray["tray"] == TRAY_NAME == "carried_unvoted"
    assert tray["active_node_id"] == "n2"
    assert [item["ce_id"] for item in tray["items"]] == [env.ce1]
    item = tray["items"][0]
    assert item["status"] == "carried_unvoted"
    assert item["shape"] == "3a" and item["node_id"] == "n1"
    assert item["q_id"] == env.q1
    assert (item["stands"], item["rebutted"]) == (2, 1)


def test_tray_is_visible_in_board_view(tmp_path):
    env = _room(tmp_path)
    _revise(env)
    view = env.service.view(env.board_id)
    assert json.loads(json.dumps(view)) == view
    assert view["tray"]["tray"] == "carried_unvoted"
    assert [item["ce_id"] for item in view["tray"]["items"]] == [env.ce1]
    # the losing CE is recorded in the sidecar, never carried to the tray
    assert env.ce2 not in [i["ce_id"] for i in view["tray"]["items"]]


def test_empty_revision_means_empty_tray_not_error(tmp_path):
    service = make_service(tmp_path)
    opened = service.open_board("Justice")
    bid = opened.board_id
    machine = service.machine(bid)
    machine.enroll_handle("Cephalus")
    service.claim_original(bid, THRASYMACHUS, claimant_display="Cephalus")
    service.revise(bid, "Justice is reciprocity.",
                   claimant_display="Cephalus")
    assert service.tray(bid)["items"] == []
    assert service.view(bid)["tray"]["items"] == []


def test_tray_on_unknown_board_refuses(tmp_path):
    env = _room(tmp_path)
    with pytest.raises(UnknownBoard):
        env.service.tray("justice--ghost--999")


# -- AC2a: press attaches the unvoted item to the active node as a new Q ----


def test_press_opens_a_new_ballot_on_the_active_node(tmp_path):
    env = _room(tmp_path)
    _revise(env)
    journal_before = len(env.service.journals.read_all(env.board_id))
    pressed = env.service.press_tray_item(env.board_id, env.ce1,
                                          by_display="Thrasymachus")
    assert pressed.node_id == "n2"
    assert pressed.shape == "3a"
    assert pressed.ce_id != env.ce1 and pressed.q_id != env.q1
    state = env.service.state(env.board_id)
    assert state.ces[pressed.ce_id].node_id == "n2"
    assert state.questions[pressed.q_id].status == "open"
    assert state.questions[pressed.q_id].subject == pressed.ce_id
    # the pressed item leaves the tray; the journal grew by the new Q only
    assert env.service.tray(env.board_id)["items"] == []
    added = [e["type"] for e in
             env.service.journals.read_all(env.board_id)[journal_before:]]
    assert added == ["q_opened"]
    # press is logged as a system entry (ids only, never voice)
    entry = env.service.read_system_log(env.board_id)[-1]
    assert entry["type"] == TRAY_PRESSED == "tray_pressed"
    assert entry["payload"]["ce_id"] == env.ce1
    assert entry["payload"]["new_q_id"] == pressed.q_id


def test_press_refusals_leave_everything_untouched(tmp_path):
    from board.machine import UnknownCounterexample

    env = _room(tmp_path)
    _revise(env)
    journal_before = len(env.service.journals.read_all(env.board_id))
    log_before = len(env.service.read_system_log(env.board_id))
    with pytest.raises(UnknownCounterexample):
        env.service.press_tray_item(env.board_id, "ce99")
    with pytest.raises(ValueError):
        # ce2 lost its vote: recorded in the sidecar, never in the tray
        env.service.press_tray_item(env.board_id, env.ce2)
    env.service.press_tray_item(env.board_id, env.ce1)
    with pytest.raises(ValueError):
        env.service.press_tray_item(env.board_id, env.ce1)
    assert len(env.service.journals.read_all(env.board_id)) \
        == journal_before + 1
    assert len(env.service.read_system_log(env.board_id)) == log_before + 1


# -- AC2b: discard writes a system-log entry --------------------------------


def test_discard_logs_and_touches_no_verdict_state(tmp_path):
    env = _room(tmp_path)
    _revise(env)
    journal_before = len(env.service.journals.read_all(env.board_id))
    meta_before = len(env.service.meta.read_events(env.board_id))
    result = env.service.discard_tray_item(env.board_id, env.ce1)
    assert result["ce_id"] == env.ce1 and result["discarded"] is True
    assert env.service.tray(env.board_id)["items"] == []
    assert len(env.service.journals.read_all(env.board_id)) == journal_before
    assert len(env.service.meta.read_events(env.board_id)) == meta_before
    entry = env.service.read_system_log(env.board_id)[-1]
    assert entry["type"] == TRAY_DISCARDED == "tray_discarded"
    assert entry["payload"]["ce_id"] == env.ce1
    assert entry["payload"]["origin"] == "system"
    banned = {"text", "display", "reason", "ballots", "claimed_by"}
    assert not (set(entry["payload"]) & banned)


def test_discard_twice_refuses_and_a_press_after_discard_refuses(tmp_path):
    env = _room(tmp_path)
    _revise(env)
    env.service.discard_tray_item(env.board_id, env.ce1)
    with pytest.raises(ValueError):
        env.service.discard_tray_item(env.board_id, env.ce1)
    with pytest.raises(ValueError):
        env.service.press_tray_item(env.board_id, env.ce1)


def test_press_refuses_on_a_closed_board_but_discard_still_logs(tmp_path):
    env = _room(tmp_path)
    _revise(env)
    q = env.service.propose_close(env.board_id,
                                  opened_by=env.h["Cephalus"])
    env.service.cast_vote(env.board_id, q, "for",
                          handle_id=env.h["Cephalus"])
    env.service.cast_vote(env.board_id, q, "for",
                          handle_id=env.h["Polemarchus"])
    assert env.service.state(env.board_id).status == "closed"
    from board.machine import BoardClosed
    with pytest.raises(BoardClosed):
        env.service.press_tray_item(env.board_id, env.ce1)
    # discard is log-only, so it still lands on a terminal board
    result = env.service.discard_tray_item(env.board_id, env.ce1)
    assert result["discarded"] is True
    assert env.service.read_system_log(env.board_id)[-1]["type"] \
        == TRAY_DISCARDED


# -- AC3: tray contents affect neither verdicts nor the canvas live path ----


def test_tray_reads_change_no_verdict_state(tmp_path):
    import board.verdicts as V

    env = _room(tmp_path)
    _revise(env)

    def verdicts():
        state = env.service.state(env.board_id)
        return {
            q_id: (dict(V.tally(state, q_id)), len(V.census(state, q_id)))
            for q_id in state.questions
        }, {nid: V.is_refuted(state, nid) for nid in state.nodes}

    before = verdicts()
    journal_before = len(env.service.journals.read_all(env.board_id))
    meta_before = len(env.service.meta.read_events(env.board_id))
    log_before = len(env.service.system.read_events(env.board_id))
    env.service.tray(env.board_id)
    env.service.view(env.board_id)
    env.service.scoreboard(env.board_id)
    assert verdicts() == before
    assert len(env.service.journals.read_all(env.board_id)) == journal_before
    assert len(env.service.meta.read_events(env.board_id)) == meta_before
    assert len(env.service.system.read_events(env.board_id)) == log_before


def test_tray_items_stay_off_the_canvas_live_path(tmp_path):
    env = _room(tmp_path)
    _revise(env)
    view = env.service.view(env.board_id)
    tray_ids = [item["ce_id"] for item in view["tray"]["items"]]
    assert tray_ids == [env.ce1]
    # tray items are not nodes, open no live questions, touch no canvas file
    assert not (set(tray_ids) & {n["node_id"] for n in view["nodes"]})
    assert all(q["q_id"] != env.q1 or q["status"] == "frozen"
               for q in view["questions"])
    assert all(q["subject"] not in tray_ids or q["status"] != "open"
               for q in view["questions"])
    assert env.service.state(env.board_id).canvas is None
    # the superseded node's frozen question still refuses votes
    with pytest.raises(NodeFrozen):
        env.service.machine(env.board_id).cast(
            env.q1, env.h["Cephalus"], "explicit", "rebutted")


def test_close_canvas_carries_no_tray_only_entries(tmp_path):
    env = _room(tmp_path)
    _revise(env)
    env.service.press_tray_item(env.board_id, env.ce1)
    pressed_q = env.service.state(env.board_id).nodes["n2"].ce_ids
    assert len(pressed_q) == 1
    q = env.service.propose_close(env.board_id,
                                  opened_by=env.h["Cephalus"])
    env.service.cast_vote(env.board_id, q, "for",
                          handle_id=env.h["Cephalus"])
    env.service.cast_vote(env.board_id, q, "for",
                          handle_id=env.h["Polemarchus"])
    state = env.service.state(env.board_id)
    assert state.status == "closed"
    canvas = state.canvas
    # the canvas is built from nodes + questions only: no tray marker leaks
    blob = json.dumps(canvas)
    assert "carried_unvoted" not in blob
    assert "tray_pressed" not in blob
    assert {n["node_id"] for n in canvas["nodes"]} == set(state.nodes)
    # the pressed item re-entered the live path as a real open Q, so close
    # snapshots it as carried_unresolved; the frozen original stays history
    assert [row["node_id"] for row in state.carried_unresolved] == ["n2"]


def test_tray_survives_a_reload_from_disk(tmp_path):
    from tests.sdf5_stubs import make_service as rebuild

    env = _room(tmp_path)
    _revise(env)
    before = env.service.tray(env.board_id)
    rebuilt = rebuild(env.service.root, chain=env.service.chain)
    assert rebuilt.tray(env.board_id) == before
    assert rebuilt.view(env.board_id)["tray"] == \
        env.service.view(env.board_id)["tray"]
