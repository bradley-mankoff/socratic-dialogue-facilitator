"""SDF-16 F1–F8 — the web provider: keyed-only, one call per trigger,
labeled one-voice results, failures as data. All stubbed; the autouse
``no_live_network`` guard stands behind every test here."""

from __future__ import annotations

import json

import pytest

from dictionary.transport import TransportError
from search.backend import (
    BRAVE_SEARCH_API,
    BraveSearchBackend,
    brave_headers,
    brave_search_url,
    clamp_limit,
    parse_brave,
)
from search.errors import MissingSearchKey
from search.model import (
    WEB_RESULT_LABEL,
    WEB_SEARCH_KIND,
    WEB_SOURCE,
    CounterexampleResult,
    WebHit,
)
from tests.search_stubs import (
    BRAVE_KEY,
    TS,
    StubSearchTransport,
    brave_response,
    make_provider,
    raw_response,
)

AUTH_HEADER = "X-Subscription-Token"


# -- F1 keyed-only construction -------------------------------------------

def test_blank_or_none_key_is_refused_at_construction():
    with pytest.raises(MissingSearchKey):
        BraveSearchBackend(None)
    with pytest.raises(MissingSearchKey):
        BraveSearchBackend("")
    with pytest.raises(MissingSearchKey):
        BraveSearchBackend("   ")
    with pytest.raises(MissingSearchKey):
        BraveSearchBackend(123)


def test_construction_makes_zero_calls():
    stub = StubSearchTransport([brave_response()])
    BraveSearchBackend(BRAVE_KEY, stub, clock=lambda: TS)
    assert stub.calls == []


# -- F2/F3 one explicit call, token in header, never in URL ----------------

def test_explicit_search_fires_exactly_one_request_with_header_token():
    stub = StubSearchTransport([brave_response()])
    backend = BraveSearchBackend(BRAVE_KEY, stub, clock=lambda: TS)
    backend.search("justice")
    assert len(stub.calls) == 1
    url, headers = stub.calls[0]
    assert url.startswith(BRAVE_SEARCH_API)
    assert headers == {AUTH_HEADER: BRAVE_KEY}
    # the token never rides the URL
    assert BRAVE_KEY not in url and AUTH_HEADER not in url


def test_two_triggers_cost_two_calls_not_one_cached_answer():
    stub = StubSearchTransport([brave_response(), brave_response()])
    backend = BraveSearchBackend(BRAVE_KEY, stub, clock=lambda: TS)
    backend.search("justice")
    backend.search("justice", query="justice thrasymachus")
    assert len(stub.calls) == 2


# -- F4 query + limit shapes -----------------------------------------------

def test_default_query_is_x_plus_counterexample():
    stub = StubSearchTransport([brave_response()])
    backend = BraveSearchBackend(BRAVE_KEY, stub, clock=lambda: TS)
    result = backend.search("justice")
    assert result.query == "justice counterexample"
    assert "q=justice%20counterexample" in stub.calls[0][0]


def test_explicit_query_is_used_verbatim():
    stub = StubSearchTransport([brave_response()])
    backend = BraveSearchBackend(BRAVE_KEY, stub, clock=lambda: TS)
    result = backend.search("justice", query="justice thrasymachus stronger")
    assert result.query == "justice thrasymachus stronger"
    assert "justice%20thrasymachus%20stronger" in stub.calls[0][0]


def test_limit_is_clamped_into_brave_window():
    assert clamp_limit(0) == 1
    assert clamp_limit(-5) == 1
    assert clamp_limit(1) == 1
    assert clamp_limit(5) == 5
    assert clamp_limit(20) == 20
    assert clamp_limit(100) == 20
    stub = StubSearchTransport([brave_response()])
    backend = BraveSearchBackend(BRAVE_KEY, stub, clock=lambda: TS)
    backend.search("justice", limit=100)
    assert "count=20" in stub.calls[0][0]
    with pytest.raises(ValueError):
        backend.search("justice", limit="many")


def test_brave_search_url_shape_is_pinned():
    assert brave_search_url("justice counterexample", 5) == (
        f"{BRAVE_SEARCH_API}?q=justice%20counterexample&count=5")
    assert brave_headers(BRAVE_KEY) == {AUTH_HEADER: BRAVE_KEY}


# -- F5 labeled results -----------------------------------------------------

def test_results_are_labeled_one_voice_web_search():
    result = make_provider(clock=lambda: TS).search("justice")
    assert result.state == "ok"
    assert result.kind == WEB_SEARCH_KIND
    assert result.canonical is False
    assert result.label == WEB_RESULT_LABEL
    assert result.engine == "brave"
    assert result.source == WEB_SOURCE
    assert result.retrieved_at == TS
    assert len(result.hits) == 3
    first = result.hits[0]
    assert isinstance(first, WebHit)
    assert first.kind == WEB_SEARCH_KIND
    assert first.source == WEB_SOURCE == "brave-web"
    assert first.canonical is False
    assert first.retrieved_at == TS
    payload = result.to_dict()
    # vocabulary disjoint from dictionary canonicals
    assert "dictionary-chain" not in json.dumps(payload)
    assert "senses" not in payload and "cites" not in payload
    assert "empty_reason" not in payload


# -- F6 failures are data, never raised -------------------------------------

def test_http_5xx_and_401_become_unavailable_with_detail():
    for status in (500, 503, 401):
        stub = StubSearchTransport([raw_response("", status=status)])
        backend = BraveSearchBackend(BRAVE_KEY, stub, clock=lambda: TS)
        result = backend.search("justice")
        assert result.state == "unavailable"
        assert result.detail == f"HTTP {status}"
        assert result.hits == []


def test_malformed_json_becomes_unavailable_with_decode_detail():
    stub = StubSearchTransport([raw_response("<html>not json</html>")])
    backend = BraveSearchBackend(BRAVE_KEY, stub, clock=lambda: TS)
    result = backend.search("justice")
    assert result.state == "unavailable"
    assert result.detail is not None and "invalid JSON" in result.detail


def test_non_object_json_payload_becomes_unavailable():
    stub = StubSearchTransport([raw_response('["a", "b"]')])
    backend = BraveSearchBackend(BRAVE_KEY, stub, clock=lambda: TS)
    result = backend.search("justice")
    assert result.state == "unavailable"
    assert result.detail == "payload is not a JSON object"


def test_transport_failure_becomes_unavailable_never_raises():
    stub = StubSearchTransport([TransportError("URLError: name resolution failed")])
    backend = BraveSearchBackend(BRAVE_KEY, stub, clock=lambda: TS)
    result = backend.search("justice")
    assert result.state == "unavailable"
    assert result.detail is not None
    assert "TransportError" in result.detail
    assert "name resolution failed" in result.detail


# -- F7 explicit empty --------------------------------------------------------

def test_missing_or_empty_web_results_is_the_empty_state():
    stub = StubSearchTransport([raw_response("{}"), brave_response()])
    stub.responses[1] = raw_response(json.dumps({"web": {"results": []}}))
    backend = BraveSearchBackend(BRAVE_KEY, stub, clock=lambda: TS)
    first = backend.search("justice")
    second = backend.search("justice")
    assert first.state == "empty" and first.hits == [] and first.detail is None
    assert second.state == "empty" and second.hits == []


def test_non_object_rows_are_skipped_not_crashed():
    payload = {"web": {"results": ["junk", {"title": "t", "url": "u",
                                            "description": "d"}]}}
    stub = StubSearchTransport([raw_response(json.dumps(payload))])
    backend = BraveSearchBackend(BRAVE_KEY, stub, clock=lambda: TS)
    result = backend.search("justice")
    assert result.state == "ok"
    assert [h.title for h in result.hits] == ["t"]


# -- F8 round-trips ------------------------------------------------------------

def test_round_trips_for_all_three_shapes():
    retrieved = TS
    hit = WebHit(title="t", url="u", snippet="s", engine="brave",
                 retrieved_at=retrieved)
    ok = CounterexampleResult(x="justice", query="q", state="ok", hits=[hit],
                              detail=None, engine="brave",
                              retrieved_at=retrieved)
    empty = CounterexampleResult(x="justice", query="q", state="empty",
                                 detail=None, engine="brave",
                                 retrieved_at=retrieved)
    unavailable = CounterexampleResult(x="justice", query="q",
                                       state="unavailable",
                                       detail="HTTP 401", engine="brave",
                                       retrieved_at=retrieved)
    for result in (ok, empty, unavailable):
        again = CounterexampleResult.from_dict(result.to_dict())
        assert again == result
    assert WebHit.from_dict(hit.to_dict()) == hit


def test_parse_brave_shapes_fixture_rows_in_engine_order():
    payload = json.loads(brave_response().body)
    result = parse_brave(payload, x="justice", query="justice counterexample",
                         engine="brave", retrieved_at=TS)
    assert [h.title for h in result.hits] == [
        "Thrasymachus on justice — a counterexample primer",
        "Cephalus's debts: the returning deposit case",
        "Robin Hood accounting as a 3b counterexample",
    ]
    assert [h.snippet.startswith(("A city", "Returning", "Redistributive"))
            for h in result.hits] == [True, True, True]


def test_search_backend_protocol_holds_for_both_backends():
    from search.backend import SearchBackend

    assert isinstance(make_provider(clock=lambda: TS), SearchBackend)


def test_live_default_transport_is_blocked_by_no_live_network():
    """F26 seed: the default transport cannot silently bypass the gate.

    The autouse guard raises AssertionError; the backend must NOT swallow
    it into ``unavailable`` (only TransportError is folded to data)."""
    backend = BraveSearchBackend(BRAVE_KEY)
    with pytest.raises(AssertionError):
        backend.search("justice")
