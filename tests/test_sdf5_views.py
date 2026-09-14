"""Views: what SDF-10 gets to render, and the guarantees it relies on.

Every value is JSON-able, every verdict number is *surfaced* from
``board.verdicts`` rather than re-derived here, and producing a view changes
nothing — no journal line, no sidecar line, no transport call. The registry
mirror is deliberately excluded from the board view (it can be stale); only
:func:`server.service.BoardService.sync_registry` writes it, and
``boards_view`` is the one place the mirror is allowed to answer.
"""

from __future__ import annotations

import json

import pytest

from server.errors import UnknownBoard
from server.views import boards_view, canonicals_view
from tests.sdf5_stubs import S0, THRASYMACHUS, empty_chain, make_service


@pytest.fixture
def live(sdf5_open):
    """Board with a claim, two counterexamples and a mixed ballot set."""
    ctx = sdf5_open
    service, machine, h = ctx.service, ctx.machine, ctx.h
    service.claim_canonical(ctx.board_id, claimant_display="Cephalus")
    ce, q = machine.open_refutation_q("n1", "3a", opened_by=h["Cephalus"])
    machine.cast(q, h["Cephalus"], "explicit", "stands")
    machine.cast(q, h["Polemarchus"], "explicit", "stands")
    machine.record_ambient(q, h["Thrasymachus"], "rebutted")
    return ctx


def test_board_view_is_json_complete_and_ordered(live):
    ctx = live
    view = ctx.service.view(ctx.board_id)
    assert json.loads(json.dumps(view)) == view
    for key in ("board_id", "x", "x_title", "label", "mode", "medium",
                "status", "seq", "handles", "active_node_id", "nodes",
                "questions", "canonicals", "cache"):
        assert key in view, key
    assert view["board_id"] == ctx.board_id
    assert view["x_title"] == "Justice"
    assert view["mode"] == "participates" and view["medium"] == "async"
    assert view["status"] == "open"
    assert [n["node_id"] for n in view["nodes"]] == ["n1"]
    assert [qq["q_id"] for qq in view["questions"]] == ["q1"]
    # no dataclass/tuple leaks anywhere in the payload
    _assert_plain(view)


def _assert_plain(value, path="view"):
    if isinstance(value, dict):
        for key, sub in value.items():
            assert isinstance(key, str), f"{path}: non-str key {key!r}"
            _assert_plain(sub, f"{path}.{key}")
    elif isinstance(value, list):
        for index, sub in enumerate(value):
            _assert_plain(sub, f"{path}[{index}]")
    else:
        assert value is None or isinstance(value, (str, int, float, bool)), \
            f"{path}: not JSON-plain: {type(value).__name__}"


def test_lineage_order_is_version_ascending_not_insertion(sdf5_open):
    ctx = sdf5_open
    service, bid = ctx.service, ctx.board_id
    service.claim_original(bid, THRASYMACHUS, claimant_display="Cephalus")
    service.revise(bid, "Justice is reciprocity.",
                   claimant_display="Polemarchus")
    service.revise(bid, "Justice is teaching what is good.",
                   claimant_display="Thrasymachus")
    view = service.view(bid)
    assert [n["version"] for n in view["nodes"]] == [1, 2, 3]
    assert [n["node_id"] for n in view["nodes"]] == ["n1", "n2", "n3"]
    assert [n["is_active"] for n in view["nodes"]] == [False, False, True]
    assert view["active_node_id"] == "n3"
    assert view["nodes"][0]["text"] == THRASYMACHUS
    assert view["nodes"][0]["provenance"]["kind"] == "original"
    assert view["nodes"][2]["provenance"]["gloss"] is None


def test_making_a_view_changes_nothing(live):
    ctx = live
    service, bid = ctx.service, ctx.board_id
    first = service.view(bid)
    journal_before = len(service.journals.read_all(bid))
    meta_before = len(service.meta.read_events(bid))
    stub_calls = len(service.chain.transport.calls)
    assert service.view(bid) == first
    assert len(service.journals.read_all(bid)) == journal_before
    assert len(service.meta.read_events(bid)) == meta_before
    assert len(service.chain.transport.calls) == stub_calls


def test_question_view_surfaces_verdict_counts(live):
    ctx = live
    view = ctx.service.view(ctx.board_id)
    question = view["questions"][0]
    assert question["kind"] == "refutation"
    assert question["status"] == "open"
    assert question["subject"] == "ce1"
    assert question["outcome"] is None
    assert question["opened_by"] == ctx.h["Cephalus"]
    assert question["opened_seq"] >= 1
    # 3 handles enfranchised at open; explicit beats ambient per handle
    assert question["census_size"] == 3
    assert question["tally"] == {"stands": 2, "rebutted": 1}
    node = view["nodes"][0]
    assert node["ce_ids"] == ["ce1"]
    assert node["status"] in ("open", "unrefuted", "refuted")


def test_governance_question_uses_for_against_vocabulary(sdf5_open):
    ctx = sdf5_open
    machine = ctx.machine
    q = machine.open_governance_q("mode_switch", subject="facilitates",
                                 opened_by=ctx.h["Cephalus"])
    machine.cast(q, ctx.h["Cephalus"], "explicit", "for")
    row = [r for r in ctx.service.view(ctx.board_id)["questions"]
           if r["q_id"] == q][0]
    assert row["kind"] == "mode_switch"
    assert row["tally"] == {"for": 1, "against": 0}
    assert row["subject"] == "facilitates"


def test_canonicals_view_shapes(sdf5_open):
    ctx = sdf5_open
    canonicals = ctx.service.view(ctx.board_id)["canonicals"]
    assert canonicals["state"] == "ok"
    assert canonicals["x"] == "justice"
    assert canonicals["pulled_at"] == "2026-09-13"
    first = canonicals["senses"][0]
    assert first["sense_id"] == "s0" and first["gloss"] == S0
    assert first["agrees"] == ["wiktionary", "free-dictionary"]
    assert first["n_cites"] == 2
    assert first["wiktionary_sense_no"] == 1
    assert set(first["cites"][0]) == {"source", "url", "access_date",
                                      "license", "raw", "pageid"}
    assert canonicals_view(None) == {"x": None, "state": "not_pulled",
                                     "empty_reason": None,
                                     "pulled_at": None, "senses": []}


def test_empty_x_renders_as_an_explicit_empty_panel(tmp_path):
    service = make_service(tmp_path / "store", chain=empty_chain())
    opened = service.open_board("Hypothetical")
    canonicals = service.view(opened.board_id)["canonicals"]
    assert canonicals["state"] == "empty"
    assert canonicals["empty_reason"]
    assert canonicals["senses"] == []


def test_boards_view_lists_boards_and_survives_a_restart(tmp_path):
    service = make_service(tmp_path / "store", chain=empty_chain())
    a = service.open_board("Justice", "room-a")
    b = service.open_board("Justice", "room-b")
    rows = service.boards_list("Justice")
    assert [r["label"] for r in rows] == ["room-a", "room-b"]
    assert [r["board_id"] for r in rows] == [a.board_id, b.board_id]
    for row in rows:
        assert set(row) == {"board_id", "x", "x_title", "label", "mode",
                            "medium", "status", "created_at"}
    assert json.loads(json.dumps(rows)) == rows
    rebuilt = make_service(tmp_path / "store", chain=empty_chain())
    assert boards_view(rebuilt.list_boards("Justice")) == rows
    assert [r["board_id"] for r in boards_view(rebuilt.list_boards())] == [
        a.board_id, b.board_id]


def test_sync_registry_only_writes_mirrors(sdf5_open):
    """The registry mirrors can go stale; the view never does.

    ``sync_registry`` is the SDF-6/8 contract: call it after a mode/medium or
    close effect and the mirrors catch up. It writes no verdict event and
    touches no other row.
    """
    ctx = sdf5_open
    service, bid, machine = ctx.service, ctx.board_id, ctx.machine
    service.claim_original(bid, THRASYMACHUS, claimant_display="Cephalus")
    switch = machine.open_governance_q("mode_switch",
                                       subject="facilitates",
                                       opened_by=ctx.h["Cephalus"])
    for who in ("Cephalus", "Polemarchus"):        # 2/3 census: majority
        machine.cast(switch, ctx.h[who], "explicit", "for")
    # effect applied on the machine, mirror still stale
    assert service.state(bid).mode == "facilitates"
    assert service.view(bid)["mode"] == "facilitates"
    assert service.board(bid).mode == "participates"
    journal_before = len(service.journals.read_all(bid))
    meta_before = len(service.meta.read_events(bid))
    record = service.sync_registry(bid)
    assert record.mode == "facilitates"
    assert service.board(bid).to_dict() == record.to_dict()
    assert len(service.journals.read_all(bid)) == journal_before
    assert len(service.meta.read_events(bid)) == meta_before
    # medium toggles mirror the same way
    machine.toggle_medium("live")
    assert service.board(bid).medium == "async"
    service.sync_registry(bid)
    assert service.board(bid).medium == "live"
    assert service.view(bid)["medium"] == "live"


def test_sync_registry_after_close(sdf5_open):
    ctx = sdf5_open
    service, machine, bid = ctx.service, ctx.machine, ctx.board_id
    service.claim_original(bid, THRASYMACHUS, claimant_display="Cephalus")
    close_q = machine.propose_close(opened_by=ctx.h["Cephalus"])
    for who in ("Cephalus", "Polemarchus"):        # 2/3 census: majority
        machine.cast(close_q, ctx.h[who], "explicit", "for")
    assert machine.is_closed()
    assert service.board(bid).status == "open", "stale until synced"
    assert service.view(bid)["status"] == "closed"
    assert service.sync_registry(bid).status == "closed"
    assert service.board(bid).status == "closed"


def test_view_of_an_unknown_board(tmp_path):
    service = make_service(tmp_path / "store", chain=empty_chain())
    with pytest.raises(UnknownBoard):
        service.view("nope")
    with pytest.raises(UnknownBoard):
        service.machine("nope")
    with pytest.raises(UnknownBoard):
        service.canonicals("nope")
    assert service.list_boards() == []
