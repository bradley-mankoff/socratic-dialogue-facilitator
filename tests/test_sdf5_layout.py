"""Slice layout: data homes, path safety, label minting, registry durability.

Proves the four on-disk homes exist where the plan says they do, that the
sidecar never shares a file with the verdict journal, and that the small
hand-written primitives (slug / board id / label sequence) are stable enough
to be someone else's primary key.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from board.store import JsonlStore
from dictionary.chain import build_default_chain
from server.model import (
    CLAIM_RECORDED,
    CLAIM_REVISED,
    make_board_id,
    next_label,
    slug,
)
from server.store import (
    BoardRegistry,
    CanonicalStore,
    MetaLog,
    canonicals_dir,
    registry_path,
)
from tests.sdf5_stubs import (
    TS,
    THRASYMACHUS,
    empty_chain,
    justice_chain,
    make_service,
)

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_store_dir_is_gitignored():
    """``store/`` holds durable data; it must never be committed."""
    lines = [line.strip()
             for line in (REPO_ROOT / ".gitignore").read_text().splitlines()]
    assert "store/" in lines


def test_data_homes_are_distinct_files_under_one_root(tmp_path):
    """Registry, canonicals, journal and sidecar each have their own home."""
    root = tmp_path / "store"
    assert registry_path(root) == root / "registry.json"
    assert canonicals_dir(root) == root / "canonicals"
    journals = JsonlStore(root)
    meta = MetaLog(root)
    assert journals.board_dir("b1") == meta.board_dir("b1") == root / "b1"
    assert journals.path_for("b1") == root / "b1" / "journal.jsonl"
    assert meta.path_for("b1") == root / "b1" / "meta.jsonl"
    assert journals.path_for("b1") != meta.path_for("b1")


def test_slugs_and_board_ids_are_path_safe():
    assert make_board_id("Justice", "Justice#2", 7) == "justice--justice-2--007"
    assert slug("!!!") == "x"
    assert slug("") == "x"
    assert slug("../../etc/passwd") == "etc-passwd"
    for bad in ("/", "..", " "):
        assert bad not in make_board_id("a/b c", "..x..", 1)
    assert make_board_id("a/b c", "..x..", 1) == "a-b-c--x--001"
    assert make_board_id("Justice", "justice", 1) == "justice--justice--001"


def test_next_label_sequence():
    label = next_label(set(), "justice")
    assert label == "justice"
    label2 = next_label({"justice"}, "justice")
    assert label2 == "justice#2"
    assert next_label({"justice", "justice#2"}, "justice") == "justice#3"
    # an untouched base is returned unchanged, even beside other labels
    assert next_label({"justice"}, "thrasy-room") == "thrasy-room"
    # occupancy is judged the way the registry keys: case/whitespace-insensitive
    assert next_label({"Justice"}, "justice") == "justice#2"


def test_registry_persists_atomically_and_reloads(tmp_path):
    path = registry_path(tmp_path / "store")
    registry = BoardRegistry(path)
    record = registry.reserve(x="Justice", x_title="Justice",
                              label="room-a", medium="live")
    assert record.status == "open" and record.board_id
    assert record.medium == "live"
    assert not list(path.parent.glob("*.tmp")), "temp file left behind"

    reloaded = BoardRegistry(path)
    assert reloaded.get("justice", "room-a").to_dict() == record.to_dict()
    assert reloaded.counter == registry.counter
    # the counter never rewinds, so a board_id is never reused
    third = reloaded.reserve(x="Justice", x_title="Justice", label="room-b")
    assert third.board_id != record.board_id
    assert json.loads(path.read_text())["counter"] == 2


def test_registry_rejects_duplicate_label_and_bogus_mirrors(tmp_path):
    registry = BoardRegistry(registry_path(tmp_path))
    registry.reserve(x="Justice", x_title="Justice", label="room-a")
    with pytest.raises(Exception) as exc:
        registry.reserve(x="Justice", x_title="Justice", label="room-a")
    assert type(exc.value).__name__ == "DuplicateLabel"
    board_id = registry.get("Justice", "room-a").board_id
    with pytest.raises(ValueError):
        registry.mark(board_id, active_node_id="n1")   # verdict state is not a mirror
    with pytest.raises(ValueError):
        registry.mark(board_id, bogus="x")
    assert registry.mark(board_id, medium="live").medium == "live"


def test_canonical_store_first_write_wins(tmp_path):
    """A cached X is never re-pulled, even by a fresh store object."""
    root = tmp_path / "store"
    stub_chain = justice_chain()
    store = CanonicalStore(root, chain=stub_chain)
    first = store.get("justice")
    assert first["state"] == "ok" and first["x"] == "justice"
    assert len(stub_chain.transport.calls) == 2
    # a second store over the same root reads the disk cache: zero new calls
    calls_now = len(stub_chain.transport.calls)
    second = CanonicalStore(root, chain=build_default_chain(
        _exploding_transport(), clock=lambda: "2026-09-13"))
    assert second.get("Justice") == first
    assert len(stub_chain.transport.calls) == calls_now
    assert (canonicals_dir(root) / "justice.json").exists()


def _exploding_transport():
    from tests.stubs import StubTransport

    class Boom(StubTransport):
        def get(self, url):        # any pull from here is a cache miss
            raise AssertionError("canonical cache must not re-pull")
    return Boom({})


def test_slug_collision_never_clobbers_another_x(tmp_path):
    """``"a b"`` and ``"a-b"`` share a slug but are different X's.

    Both normalize distinctly, so writing the second must not silently replace
    the first board's canonical snapshot.
    """
    root = tmp_path / "store"
    space = make_service(root, chain=justice_chain())
    a = space.open_board("a b")
    assert space.canonicals(a.board_id)["x"] == "a b"
    hyphen_chain = justice_chain()
    hyphen = make_service(root, chain=hyphen_chain)
    b = hyphen.open_board("a-b")
    assert a.board_id != b.board_id
    assert a.record.x_norm == "a b" and b.record.x_norm == "a-b"
    # neither board lost its definitions
    assert hyphen.canonicals(b.board_id)["x"] == "a-b"
    assert hyphen.canonicals(a.board_id)["x"] == "a b"
    assert hyphen.view(a.board_id)["canonicals"]["x"] == "a b"
    names = sorted(p.name for p in (root / "canonicals").glob("*.json"))
    assert len(names) == 2 and all(n.startswith("a-b") for n in names), names


def test_meta_log_only_holds_slice_event_types(tmp_path):
    meta = MetaLog(tmp_path)
    event = meta.append_event("b1", "claim_recorded", {"node_id": "n1"},
                             ts=TS)
    assert event == {"seq": 1, "type": "claim_recorded", "board_id": "b1",
                     "ts": TS, "payload": {"node_id": "n1"}}
    with pytest.raises(ValueError):
        meta.append_event("b1", "ballot_cast", {"q_id": "q1"}, ts=TS)
    with pytest.raises(ValueError):
        meta.read_events("b1", "board_closed")
    assert meta.read_events("b1", "claim_revised") == []
    assert len(meta.read_events("b1")) == 1


def test_torn_sidecar_tail_does_not_touch_the_journal(tmp_path):
    """Crash tolerance is inherited, and the two logs fail independently.

    A half-written meta line is dropped by the shared ``JsonlStore`` repair;
    the verdict journal keeps every event and still folds to the live state.
    """
    from board.machine import fold_events

    root = tmp_path / "store"
    service = make_service(root, chain=empty_chain())
    opened = service.open_board("Justice")
    bid = opened.board_id
    service.claim_original(bid, THRASYMACHUS, claimant_display="Cephalus")
    journal_before = service.journals.read_all(bid)
    bytes_before = service.journals.path_for(bid).read_bytes()

    with open(service.meta.path_for(bid), "a") as fh:
        fh.write('{"seq":2,"type":"claim_revised","pay')   # torn line

    with pytest.warns(UserWarning, match="torn journal tail"):
        events = service.meta.read_events(bid)
    assert [(e["seq"], e["type"]) for e in events] == [(1, CLAIM_RECORDED)]
    assert service.journals.read_all(bid) == journal_before
    assert service.journals.path_for(bid).read_bytes() == bytes_before
    assert fold_events(journal_before) == service.state(bid)

    # and the log stays usable: the next append renumbers from what survived
    # (the tail was already repaired by the read above, so no further warning)
    service.revise(bid, "Justice is reciprocity.",
                   claimant_display="Polemarchus")
    assert [(e["seq"], e["type"]) for e in service.meta.read_events(bid)] == [
        (1, CLAIM_RECORDED), (2, CLAIM_RECORDED), (3, CLAIM_REVISED)]
