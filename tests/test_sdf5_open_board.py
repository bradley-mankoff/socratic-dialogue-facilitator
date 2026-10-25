"""Board open/create: registry identity, canonical pull, medium per board.

The board is keyed by ``(normalize_x(X), label)``; opening is get-or-create
and never destructive. Canonicals are pulled before anything is written, so a
dead dictionary leaves no half-open board (plan §2.5 step order).
"""

from __future__ import annotations

import json

import pytest

from board.machine import EVENT_TYPES, fold_events
from dictionary.chain import build_default_chain
from server.model import OPS_EVENT_TYPES
from server.service import BoardService
from tests.sdf5_stubs import (
    DATE,
    S0,
    fixed_clock,
    justice_chain,
    justice_stub,
    make_service,
)


def _service(tmp_path, stub=None):
    stub = stub if stub is not None else justice_stub()
    return make_service(tmp_path / "store",
                        chain=build_default_chain(stub, clock=lambda: DATE))


def test_open_creates_record_and_journal(tmp_path):
    service = _service(tmp_path)
    opened = service.open_board("Justice (Republic Book I)", "room-a")
    assert opened.created is True
    record = opened.record
    assert record.board_id == service.journals.board_dir(record.board_id).name
    assert record.x_norm == "justice (republic book i)"
    assert record.x_title == "Justice (Republic Book I)"
    events = service.journals.read_all(record.board_id)
    assert [e["type"] for e in events] == ["board_created"]
    assert events[0]["payload"]["x_title"] == "Justice (Republic Book I)"
    assert (tmp_path / "store" / "registry.json").exists()


def test_open_pulls_canonicals_once(tmp_path):
    stub = justice_stub()
    service = _service(tmp_path, stub)
    opened = service.open_board("Justice")
    snapshot = service.canonicals(opened.board_id)
    assert snapshot["state"] == "ok"
    assert snapshot["senses"][0]["gloss"] == S0
    assert snapshot["pulled_at"] == DATE
    assert len(stub.calls) == 2, "one pull per source, per board open"
    # a read of the same board costs nothing further
    service.view(opened.board_id)
    assert len(stub.calls) == 2


def test_open_is_get_or_create_per_key(tmp_path):
    stub = justice_stub()
    service = _service(tmp_path, stub)
    first = service.open_board("Justice", "room-a")
    again = service.open_board("Justice", "room-a")
    assert again.created is False
    assert again.board_id == first.board_id
    assert len(service.journals.read_all(first.board_id)) == 1
    assert service.state(first.board_id).nodes == {}
    assert len(stub.calls) == 2, "the same board must not re-pull"


def test_reopen_ignores_medium_argument(tmp_path):
    """Medium is chosen once at creation; changing it is a direct write."""
    service = _service(tmp_path)
    opened = service.open_board("Justice", "room-a", medium="async")
    again = service.open_board("Justice", "room-a", medium="live")
    assert again.created is False
    assert service.state(opened.board_id).medium == "async"
    assert again.view["medium"] == "async"


def test_medium_is_stored_per_board(tmp_path):
    service = _service(tmp_path)
    first = service.open_board("Justice", "room-a", medium="async")
    second = service.open_board("Justice", "room-b", medium="live")
    assert first.record.medium == "async"
    assert second.record.medium == "live"
    assert service.state(first.board_id).medium == "async"
    assert service.state(second.board_id).medium == "live"
    assert first.view["medium"] != second.view["medium"]
    payloads = [
        service.journals.read_all(bid)[0]["payload"]["medium"]
        for bid in (first.board_id, second.board_id)
    ]
    assert payloads == ["async", "live"]
    # same X, different medium: two independent boards, one shared cache
    assert service.canonicals(first.board_id) == \
        service.canonicals(second.board_id)


def test_invalid_arguments_write_nothing(tmp_path):
    stub = justice_stub()
    root = tmp_path / "store"
    service = make_service(root, chain=build_default_chain(stub,
                                                           clock=lambda: DATE))
    with pytest.raises(ValueError):
        service.open_board("Justice", "room-a", medium="realtime")
    with pytest.raises(ValueError):
        service.open_board("   ")
    with pytest.raises(ValueError):
        service.open_board("", "room-a")
    with pytest.raises(ValueError):
        service.open_board("Justice", "   ")
    assert service.registry.boards == {}
    assert not root.exists() or not list(root.glob("justice--*"))
    assert not (root / "canonicals").exists()
    assert stub.calls == []


def test_fresh_board_has_no_canvas_or_nodes(tmp_path):
    service = _service(tmp_path)
    opened = service.open_board("Justice")
    state = service.state(opened.board_id)
    assert state.canvas is None
    assert state.carried_unresolved is None
    assert state.nodes == {}
    assert state.active_node_id is None
    assert opened.view["nodes"] == []
    assert opened.view["questions"] == []
    assert opened.view["status"] == "open"
    assert opened.view["seq"] == 1


def test_meta_log_is_separate_from_journal(tmp_path):
    """Two logs, two seq counters, one fold: a foreign line would break replay."""
    service = _service(tmp_path)
    opened = service.open_board("Justice")
    bid = opened.board_id
    service.claim_original(bid, "Justice is paying your debts.",
                          claimant_display="Cephalus")
    service.revise(bid, "Justice is telling the truth.",
                   claimant_display="Cephalus")
    journal = service.journals.read_all(bid)
    meta = service.meta.read_events(bid)
    assert {e["type"] for e in journal} <= set(EVENT_TYPES)
    assert {e["type"] for e in meta} <= set(OPS_EVENT_TYPES)
    assert [e["type"] for e in meta] == ["claim_recorded", "claim_recorded",
                                         "claim_revised"]
    assert [e["seq"] for e in meta] == [1, 2, 3]
    assert [e["seq"] for e in journal][:3] == [1, 2, 3]
    assert fold_events(journal) == service.state(bid)
    # the two logs never share a file
    assert service.journals.path_for(bid) != service.meta.path_for(bid)
    assert json.dumps([e for e in meta])


def test_service_survives_a_corrupt_registry(tmp_path):
    """A torn registry rewrites cleanly instead of taking the factory down."""
    root = tmp_path / "store"
    service = make_service(root, chain=justice_chain())
    opened = service.open_board("Justice")
    (root / "registry.json").write_text("{ not json", encoding="utf-8")
    rebuilt = BoardService(root, chain=justice_chain(), clock=fixed_clock())
    assert rebuilt.registry.boards == {}
    fresh = rebuilt.open_board("Courage")
    assert fresh.created is True
    assert rebuilt.registry.by_id(fresh.board_id) is not None
    assert opened.board_id not in rebuilt.registry.boards
