"""End-to-end dictionary chain over stubbed HTTP (SDF-3 acceptance proof)."""

import pytest

from dictionary.chain import build_default_chain, distinct_sources
from dictionary.transport import HttpResponse, TransportError
from tests.stubs import StubTransport, json_response

DATE = "2026-09-13"
V = "The fair and honest administration of the law by individuals."
I = "The fair and honest administration of the law by courts."
P = "A judge of a court of law."
G = "The fair and honest administration of the law."
G2 = "A judge of a court of law."
T = "To punish a person appropriately for an offense."


def _stub(wik=None, freed=None, mw=None):
    responses = {}
    if wik is not None:
        responses["en.wiktionary.org"] = wik
    if freed is not None:
        responses["dictionaryapi.dev"] = freed
    if mw is not None:
        responses["dictionaryapi.com"] = mw
    return StubTransport(responses)


def _wik_fixture():
    return json_response("wiktionary_justice.json")


def _fd_fixture():
    return json_response("freedict_justice.json")


def _chain(stub, **kwargs):
    return build_default_chain(stub, clock=lambda: DATE, **kwargs)


def test_full_convergence_over_stubbed_http():
    stub = _stub(wik=_wik_fixture(), freed=_fd_fixture())
    result = _chain(stub).get("Justice")
    assert result.state == "ok"
    assert result.x == "justice"
    assert result.empty_reason is None
    assert [s.gloss for s in result.senses] == [V, P, I, T]
    assert [distinct_sources(s) for s in result.senses] == [2, 2, 1, 1]
    assert [s.wiktionary_sense_no for s in result.senses] == [1, 3, 2, None]
    for sense in result.senses:
        assert sense.cites
        for cite in sense.cites:
            assert cite.source
            assert cite.url
            assert cite.access_date == DATE == result.pulled_at
            assert cite.license
    first = result.senses[0]
    assert [c.source for c in first.cites] == ["wiktionary", "free-dictionary"]
    assert first.cites[0].url == "https://en.wiktionary.org/wiki/justice"
    assert first.cites[0].license == "CC BY-SA 3.0"
    assert (
        first.cites[1].url
        == "https://api.dictionaryapi.dev/api/v2/entries/en/justice"
    )
    assert first.cites[1].license == "unverified-upstream"


def test_dictionaryapi_522_degrades_to_wiktionary_senses():
    stub = _stub(wik=_wik_fixture(), freed=HttpResponse(522, "", ""))
    chain = _chain(stub)
    result = chain.get("justice")
    assert result.state == "ok"
    assert [s.gloss for s in result.senses] == [V, I, P]
    assert all(distinct_sources(s) == 1 for s in result.senses)
    assert all(
        cite.source != "free-dictionary"
        for sense in result.senses
        for cite in sense.cites
    )
    outcomes = {o.source: o for o in result.outcomes}
    assert outcomes["wiktionary"].status == "ok"
    assert outcomes["free-dictionary"].status == "unavailable"
    assert outcomes["free-dictionary"].detail == "HTTP 522"
    # failures are cached too: no re-pull mid-dialogue
    assert chain.get("justice") is result
    assert len(stub.calls) == 2


def test_wiktionary_down_degrades_to_free_dictionary():
    stub = _stub(wik=TransportError("dns failure"), freed=_fd_fixture())
    result = _chain(stub).get("justice")
    assert result.state == "ok"
    assert [s.gloss for s in result.senses] == [G, G2, T]
    assert all(distinct_sources(s) == 1 for s in result.senses)
    assert all(
        cite.source == "free-dictionary"
        for sense in result.senses
        for cite in sense.cites
    )
    outcomes = {o.source: o for o in result.outcomes}
    assert outcomes["wiktionary"].status == "unavailable"
    assert "TransportError" in outcomes["wiktionary"].detail


def test_all_sources_unreachable_returns_explicit_empty_state():
    stub = _stub(wik=TransportError("dns"), freed=HttpResponse(522, "", ""))
    result = _chain(stub).get("justice")
    assert result.state == "empty"
    assert result.is_empty()
    assert result.senses == []
    assert result.empty_reason == "all_sources_unavailable"
    assert [o.status for o in result.outcomes] == ["unavailable", "unavailable"]
    assert all(o.detail for o in result.outcomes)


def test_unknown_word_returns_no_hit_empty_state():
    stub = _stub(
        wik=json_response("wiktionary_missing.json"),
        freed=HttpResponse(404, "", ""),
    )
    result = _chain(stub).get("zzzquux")
    assert result.state == "empty"
    assert result.empty_reason == "no_hit"
    assert result.senses == []
    assert [o.status for o in result.outcomes] == ["no_entry", "no_entry"]


def test_blank_x_is_rejected():
    stub = _stub(wik=_wik_fixture(), freed=_fd_fixture())
    chain = _chain(stub)
    with pytest.raises(ValueError):
        chain.get("   ")
    assert stub.calls == []


def test_second_get_served_from_cache_without_repull():
    stub = _stub(wik=_wik_fixture(), freed=_fd_fixture())
    chain = _chain(stub)
    first = chain.get("justice")
    assert len(stub.calls) == 2
    second = chain.get("justice")
    assert second is first
    assert len(stub.calls) == 2
    # case + whitespace only: the same key, so a cache hit, no re-pull
    third = chain.get("  JUSTICE  ")
    assert third is first
    assert len(stub.calls) == 2
    chain.reset_cache()
    chain.get("justice")
    assert len(stub.calls) == 4


def test_merriam_webster_excluded_by_default():
    stub = _stub(
        wik=_wik_fixture(),
        freed=_fd_fixture(),
        mw=json_response("merriam_justice.json"),
    )
    result = _chain(stub).get("justice")
    assert not any("dictionaryapi.com" in call for call in stub.calls)
    person = next(s for s in result.senses if s.gloss == P)
    assert distinct_sources(person) == 2


def test_merriam_webster_vote_ranked_first_when_key_configured():
    stub = _stub(
        wik=_wik_fixture(),
        freed=_fd_fixture(),
        mw=json_response("merriam_justice.json"),
    )
    result = _chain(stub, merriam_webster_key="test-key").get("justice")
    assert [s.gloss for s in result.senses] == [P, V, I, T]
    assert [distinct_sources(s) for s in result.senses] == [3, 2, 1, 1]
    person = result.senses[0]
    assert [c.source for c in person.cites] == [
        "wiktionary",
        "free-dictionary",
        "merriam-webster",
    ]
    mw_cite = next(c for c in person.cites if c.source == "merriam-webster")
    assert mw_cite.url == "https://www.merriam-webster.com/dictionary/justice"
    mw_calls = [call for call in stub.calls if "dictionaryapi.com" in call]
    assert mw_calls
    assert all("key=test-key" in call for call in mw_calls)
