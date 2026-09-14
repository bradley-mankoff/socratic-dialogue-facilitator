"""AC1 — a second board for the same X opens with a distinct label, sharing
the canonical cache but not a single bit of verdict state.

The two halves of the criterion are proved against each other: the transport
call count stays at the two calls of the *first* open (shared cache), while
each board keeps its own journal, its own node numbering and its own mode
(independent state). Board identity is ``(normalize_x(X), label)``, so
"Justice" and "justice" are one X, and two labels are two boards.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from dictionary.chain import build_default_chain
from server.errors import ClaimAlreadyActive, EmptyCanonicals, NoCanonicals
from server.store import canonical_path
from tests.sdf5_stubs import (
    DATE,
    S0,
    THRASYMACHUS,
    empty_chain,
    justice_chain,
    justice_stub,
    make_service,
)

X_TITLE = "Justice (Republic Book I)"
X_NORM = "justice (republic book i)"


def _service(tmp_path, stub):
    return make_service(tmp_path / "store",
                        chain=build_default_chain(stub, clock=lambda: DATE))


@pytest.fixture
def two_boards(tmp_path):
    stub = justice_stub()
    service = _service(tmp_path, stub)
    a = service.open_board(X_TITLE, "socrates-room")
    b = service.open_board(X_TITLE, "thrasy-room")
    return SimpleNamespace(service=service, stub=stub, a=a, b=b,
                           root=tmp_path / "store")


def test_second_board_gets_its_own_label_and_id(two_boards):
    ctx = two_boards
    assert ctx.a.created is True and ctx.b.created is True
    assert ctx.a.board_id != ctx.b.board_id
    assert ctx.a.record.label == "socrates-room"
    assert ctx.b.record.label == "thrasy-room"
    assert ctx.a.record.x_norm == ctx.b.record.x_norm == X_NORM
    assert [r.label for r in ctx.service.list_boards(X_TITLE)] == [
        "socrates-room", "thrasy-room"]
    assert ctx.service.journals.board_dir(ctx.a.board_id) != \
        ctx.service.journals.board_dir(ctx.b.board_id)
    assert len(ctx.stub.calls) == 2, "the second open must not re-pull"


def test_explicit_label_is_get_or_create(two_boards):
    ctx = two_boards
    again = ctx.service.open_board(X_TITLE, "thrasy-room")
    assert again.created is False
    assert again.board_id == ctx.b.board_id
    assert len(ctx.service.registry.boards) == 2
    assert len(ctx.stub.calls) == 2


def test_label_is_auto_minted_when_omitted(tmp_path):
    service = make_service(tmp_path / "store", chain=empty_chain())
    first = service.open_board("justice")
    second = service.open_board("Justice")
    third = service.open_board("  justice  ")
    labels = [first.record.label, second.record.label, third.record.label]
    assert labels == ["justice", "justice#2", "justice#3"]
    ids = {first.board_id, second.board_id, third.board_id}
    assert len(ids) == 3
    assert len(service.registry.boards) == 3


def test_canonical_cache_is_shared_and_identical(two_boards):
    ctx = two_boards
    snap_a = ctx.service.canonicals(ctx.a.board_id)
    snap_b = ctx.service.canonicals(ctx.b.board_id)
    assert snap_a == snap_b
    assert snap_a["state"] == "ok" and snap_a["senses"][0]["gloss"] == S0
    assert ctx.service.view(ctx.a.board_id)["canonicals"] == \
        ctx.service.view(ctx.b.board_id)["canonicals"]
    # one snapshot file per X, not one per board
    assert canonical_path(X_NORM, ctx.root).exists()
    assert len(list((ctx.root / "canonicals").glob("*.json"))) == 1


def test_cache_flag_tracks_how_many_boards_share_the_x(tmp_path):
    service = make_service(tmp_path / "store", chain=justice_chain())
    solo = service.open_board("Justice")
    assert solo.view["cache"] == {"shared": False, "source": "registry"}
    partner = service.open_board("Justice", "again")
    assert partner.view["cache"]["shared"] is True
    # the flag describes the X, so the first board reads back shared too
    assert service.view(solo.board_id)["cache"]["shared"] is True


def test_verdict_state_is_per_board(two_boards):
    ctx = two_boards
    claimed = ctx.service.claim_canonical(ctx.a.board_id,
                                         claimant_display="Cephalus")
    assert claimed.version == 1
    state_a = ctx.service.state(ctx.a.board_id)
    state_b = ctx.service.state(ctx.b.board_id)
    assert state_a.active_node_id == "n1"
    assert state_b.active_node_id is None and state_b.nodes == {}
    assert ctx.service.view(ctx.b.board_id)["nodes"] == []
    assert ctx.service.provenance_map(ctx.b.board_id) == {}
    # B's own first claim restarts numbering at v1: versions are per board
    fresh = ctx.service.claim_original(ctx.b.board_id, THRASYMACHUS,
                                      claimant_display="Thrasymachus")
    assert (fresh.node_id, fresh.version) == ("n1", 1)
    assert ctx.service.state(ctx.a.board_id).nodes["n1"].text == S0
    assert ctx.service.state(ctx.b.board_id).nodes["n1"].text == THRASYMACHUS
    assert ctx.service.journals.path_for(ctx.a.board_id) != \
        ctx.service.journals.path_for(ctx.b.board_id)


def test_mode_is_chosen_per_board_on_the_same_x(two_boards):
    ctx = two_boards
    assert ctx.a.record.mode == "participates"
    quiet = ctx.service.open_board(X_TITLE, "quiet-room", mode="facilitates")
    assert quiet.record.mode == "facilitates"
    assert ctx.service.state(ctx.a.board_id).mode == "participates"
    assert ctx.service.state(quiet.board_id).mode == "facilitates"
    assert ctx.service.view(quiet.board_id)["mode"] == "facilitates"
    assert [r.mode for r in ctx.service.list_boards(X_TITLE)] == [
        "participates", "participates", "facilitates"]
    # same X, three boards, still one canonical pull
    assert len(ctx.stub.calls) == 2


def test_votes_on_one_board_never_leak_to_another(two_boards):
    ctx = two_boards
    ctx.service.claim_canonical(ctx.a.board_id, claimant_display="Cephalus")
    machine_a = ctx.service.machine(ctx.a.board_id)
    h = ctx.service.state(ctx.a.board_id).handles["h1"]
    ce, q = machine_a.open_refutation_q("n1", "3a", opened_by=h.handle_id)
    machine_a.cast(q, h.handle_id, "explicit", "stands")
    questions_a = ctx.service.view(ctx.a.board_id)["questions"]
    assert [row["q_id"] for row in questions_a] == ["q1"]
    assert questions_a[0]["tally"] == {"stands": 1, "rebutted": 0}
    assert ctx.service.view(ctx.b.board_id)["questions"] == []
    assert ctx.service.state(ctx.b.board_id).ballots == {}


def test_empty_canonicals_are_shared_too(tmp_path):
    service = make_service(tmp_path / "store", chain=empty_chain())
    a = service.open_board("Sophrosyne", "room-a")
    b = service.open_board("Sophrosyne", "room-b")
    assert service.canonicals(a.board_id) == service.canonicals(b.board_id)
    assert service.canonicals(a.board_id)["state"] == "empty"
    for bid in (a.board_id, b.board_id):
        with pytest.raises(EmptyCanonicals):
            service.claim_canonical(bid, claimant_display="Cephalus")
        assert service.claim_original(bid, THRASYMACHUS,
                                     claimant_display="Cephalus").is_active
    with pytest.raises(ClaimAlreadyActive):
        service.claim_original(b.board_id, "again",
                              claimant_display="Polemarchus")


def test_deferred_pull_is_shared_when_it_finally_happens(tmp_path):
    stub = justice_stub()
    service = _service(tmp_path, stub)
    a = service.open_board("Justice", "a", pull_canonicals=False)
    b = service.open_board("Justice", "b", pull_canonicals=False)
    assert service.canonicals(a.board_id) is None
    assert a.view["canonicals"]["state"] == "not_pulled"
    assert a.view["canonicals"]["senses"] == []
    with pytest.raises(NoCanonicals):
        service.claim_canonical(a.board_id, claimant_display="Cephalus")
    # authoring an original works with nothing pulled at all
    assert service.claim_original(a.board_id, THRASYMACHUS,
                                 claimant_display="Cephalus").is_active
    assert stub.calls == []
    # one later pull serves every board on this X, at the same seq
    service.open_board("Justice", "c")
    assert len(stub.calls) == 2
    assert service.canonicals(a.board_id)["senses"][0]["gloss"] == S0
    assert service.canonicals(b.board_id) == service.canonicals(a.board_id)
    assert service.view(b.board_id)["canonicals"]["state"] == "ok"


def test_a_new_x_gets_its_own_cache_entry(tmp_path):
    stub = justice_stub()
    service = _service(tmp_path, stub)
    justice = service.open_board("Justice")
    assert len(stub.calls) == 2
    courage = service.open_board("Courage")
    assert len(stub.calls) == 4
    assert courage.record.x_norm == "courage"
    assert service.canonicals(courage.board_id)["x"] == "courage"
    assert service.canonicals(justice.board_id)["x"] == "justice"
    service.open_board("Justice", "second")     # shared: no new pull
    service.view(justice.board_id)
    assert len(stub.calls) == 4
    assert sorted(p.name for p in
                  (tmp_path / "store" / "canonicals").glob("*.json")) == [
        "courage.json", "justice.json"]


def test_second_board_survives_a_restart(two_boards):
    ctx = two_boards
    ctx.service.claim_canonical(ctx.b.board_id, claimant_display="Cephalus")
    # a chain whose transport would fail the moment anything pulls
    rebuilt = make_service(ctx.root, chain=empty_chain())
    assert rebuilt.state(ctx.b.board_id).active_node_id == "n1"
    assert rebuilt.canonicals(ctx.b.board_id)["senses"][0]["gloss"] == S0
    assert [r.label for r in rebuilt.list_boards(X_TITLE)] == [
        "socrates-room", "thrasy-room"]
    assert rebuilt.view(ctx.b.board_id)["cache"]["shared"] is True
    assert rebuilt.view(ctx.b.board_id)["nodes"][0]["text"] == S0
