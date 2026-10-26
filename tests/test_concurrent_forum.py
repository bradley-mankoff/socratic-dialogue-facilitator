"""Two people acting at the same moment never break the forum (sdf-zj6.14).

Seam: the forum's HTTP pages driven over loopback on a free port, the way
a person drives them. Reads back through the same pages, plus a fresh
SymposiumStore load from disk to prove no save was lost.
"""
from __future__ import annotations

import threading
from http.server import ThreadingHTTPServer

from server.symposium import SymposiumStore
from tests.sdf5_stubs import justice_chain, make_service
from tests.forum_http import (
    claim as _claim_one,
    enter as _enter,
    http_get as _get,
    live_forum,
    run_at_once as _run_at_once,
    start_and_tokens,
)


def _everyone_goes_in_at_once(base, tokens):
    """Every invited guest presses "Go in" at the same moment.

    The host joined at Start, so only the guests go in here.
    """
    return _run_at_once(
        {name: (lambda token=token: _enter(base, token))
         for name, token in tokens.items()}
    )


def _claim(base, sid, tokens, who, text):
    return _claim_one(base, sid, tokens[who], original=text)


def test_many_participants_going_in_at_once_all_get_in(live_forum):
    base, service = live_forum
    _invites, tokens, sid = start_and_tokens(base, guests=7)
    assert set(tokens) == {
        "Ada", "Bohdan", "Cara", "Dara", "Elif", "Farah", "Gus", "Hana",
    }
    # Every invited guest presses "Go in" at the same moment.
    results, errors = _everyone_goes_in_at_once(
        base, {name: token for name, token in tokens.items()
               if name != "Ada"})
    assert not errors, errors
    for name, location in results.items():
        assert "/symposiums/" in location, name
    # Every participant reads back the Symposium page, never the welcome page.
    for name, token in tokens.items():
        _, page, _ = _get(base + f"/symposiums/{sid}?token={token}")
        assert "could not be completed" not in page, name
        assert "A Symposium on" in page, name
        assert "Welcome," not in page, name
    # Every participant is marked as joined in the saved Symposium records.
    # Guests have no names until they name themselves in a later Bead, so
    # the records match on tokens, not names.
    fresh = SymposiumStore(service.root)
    record = fresh.get(sid)
    assert record is not None
    assert {p["token"] for p in record["participants"]} == set(
        tokens.values())
    for person in record["participants"]:
        assert person["joined"] is True, person["token"]


def test_two_first_definitions_at_once_leave_exactly_one_active(live_forum):
    base, _service = live_forum
    _invites, tokens, sid = start_and_tokens(base, guests=7)
    for token in tokens.values():
        _enter(base, token)
    results, errors = _run_at_once(
        {
            "Ada": lambda: _claim(
                base, sid, tokens, "Ada", "Justice is harmony."),
            "Bohdan": lambda: _claim(
                base, sid, tokens, "Bohdan", "Justice is order."),
        }
    )
    assert not errors, errors
    codes = sorted(status for status, _page, _headers in results.values())
    assert codes == [200, 303], results
    for _who, (status, page, _headers) in results.items():
        assert "could not be completed" not in page
        assert "Error" not in page
        if status == 200:
            assert "already" in page.lower()
            assert "active" in page.lower()
    _, page, _ = _get(base + f"/symposiums/{sid}?token={tokens['Ada']}")
    assert ("Justice is harmony." in page) != ("Justice is order." in page)


def test_concurrent_requests_leave_a_clean_journal_that_reloads(live_forum):
    base, service = live_forum
    _invites, tokens, sid = start_and_tokens(base, guests=7)
    board_id = service.registry.by_id(sid).board_id
    results, errors = _everyone_goes_in_at_once(base, tokens)
    assert not errors, errors
    results, errors = _run_at_once(
        {
            "Ada": lambda: _claim(
                base, sid, tokens, "Ada", "Justice is harmony."),
            "Cara": lambda: _claim(
                base, sid, tokens, "Cara", "Justice is fairness."),
        }
    )
    assert not errors, errors
    assert sorted(
        status for status, _page, _headers in results.values()
    ) == [200, 303]
    # The board journal's event numbers are unique and consecutive.
    journal = service.journals.read_all(board_id)
    seqs = [event["seq"] for event in journal]
    assert sorted(seqs) == list(range(1, len(seqs) + 1))
    # Reloading the board journal from disk gives the same Symposium state.
    fresh_service = make_service(service.root, chain=justice_chain())
    assert fresh_service.machine(board_id).state.to_dict() == \
        service.machine(board_id).state.to_dict()
    # Reloading the Symposium records from disk keeps every join and the board.
    fresh_records = SymposiumStore(service.root)
    record = fresh_records.get(sid)
    assert record is not None
    assert record["board_id"] == sid
    assert {p["token"] for p in record["participants"]} == set(
        tokens.values())
    assert all(p["joined"] for p in record["participants"])
    _, page, _ = _get(base + f"/symposiums/{sid}?token={tokens['Ada']}")
    assert "could not be completed" not in page


def test_reads_during_first_claim_after_restart_leave_single_active(live_forum):
    base, service = live_forum
    from web.forum import make_handler
    # Repeat over fresh Symposiums so a rare overlap becomes a certain
    # failure while the cache race is present (about one trial in three
    # shows two active definitions on the unfixed code).
    for attempt in range(6):
        word = "Justice" if attempt == 0 else f"Justice {attempt}"
        _invites, tokens, sid = start_and_tokens(base, guests=7, word=word)
        for token in tokens.values():
            _enter(base, token)
        # A forum restart empties the board-machine cache: a fresh service
        # on the same root replays the board journal from disk on first use.
        fresh = make_service(service.root, chain=justice_chain())
        restarted = ThreadingHTTPServer(("127.0.0.1", 0),
                                        make_handler(fresh))
        thread = threading.Thread(target=restarted.serve_forever,
                                  daemon=True)
        thread.start()
        try:
            base2 = f"http://127.0.0.1:{restarted.server_port}"
            calls = {
                f"read-{i}": (
                    lambda token=tokens["Bohdan"], sid=sid, base2=base2:
                    _get(base2 + f"/symposiums/{sid}?token={token}"))
                for i in range(20)
            }
            calls["Ada-claim"] = lambda: _claim(
                base2, sid, tokens, "Ada", "Justice is harmony.")
            _results, errors = _run_at_once(calls)
            assert not errors, errors
            status, page, _headers = _claim(
                base2, sid, tokens, "Bohdan", "Justice is order.")
            assert status == 200, (attempt, status, page[:500])
            assert "could not be completed" not in page, attempt
            assert "already" in page.lower(), (attempt, page[:500])
            assert "active" in page.lower(), (attempt, page[:500])
            board_id = fresh.registry.by_id(sid).board_id
            journal = fresh.journals.read_all(board_id)
            seqs = [event["seq"] for event in journal]
            assert sorted(seqs) == list(range(1, len(seqs) + 1)), attempt
            assert len(set(seqs)) == len(seqs), attempt
        finally:
            restarted.shutdown()
            thread.join()
            restarted.server_close()
