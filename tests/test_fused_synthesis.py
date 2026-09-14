"""Fused synthesis proof (SDF-3): panel-a core + panel-b aliases + panel-c hardening.

Covers the four acceptance criteria through the canonical ``get`` path and
then proves the fused aliases observe the same objects:
``lookup``/``search``, ``status``/``per_source``/``degraded``/``consensus``,
``is_empty`` as both property and call, underscore source spellings,
``check_invariant``/``render``, ``pageid``/``sense_id``, ``clear_cache``,
``default_sources``, ``cluster``/``rank_senses``, ``classify_status``/
``stability_for``, and the stdlib-only guard.
"""

import pathlib
import re

from dictionary import DictionaryChain
from dictionary.chain import (
    SourceResult,
    build_default_chain,
    cluster,
    consensus,
    default_sources,
    distinct_sources,
    rank_senses,
)
from dictionary.dedupe import JACCARD_THRESHOLD as DEDUPE_THRESHOLD
from dictionary.errors import BadSourceResponse, SourceUnavailable
from dictionary.http import Fetch, HttpResponse as HttpResponseAlias, UrlLibFetch, UrllibTransport
from dictionary.model import (
    SOURCES,
    ChainResult,
    Cite,
    Sense,
    SourceOutcome,
)
from dictionary.normalize import (
    JACCARD_THRESHOLD,
    gloss_tokens,
    jaccard,
    normalize_gloss,
    normalize_key,
    normalize_sense_text,
    normalize_term,
    normalize_text,
    normalize_x,
    tokenize,
)
from dictionary.sources import (
    RawSense,
    classify_status,
    stability_for,
    wiktionary_curid_url,
)
from dictionary.sources_util import classify_status as classify_alias
from dictionary.transport import HttpResponse, Transport, TransportError
from tests.dict_stubs import FakeTransport, chain_with
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


def _chain(stub, **kwargs):
    return build_default_chain(stub, clock=lambda: DATE, **kwargs)


# -- AC1: full convergence, ranked senses with cites (2f73f836) -------------

def test_fused_full_convergence_ranked_with_cites():
    stub = _stub(
        wik=json_response("wiktionary_justice.json"),
        freed=json_response("freedict_justice.json"),
    )
    result = _chain(stub).get("Justice")
    assert result.state == "ok"
    assert result.status == "ok"  # panel-b/c alias
    assert result.x == "justice" == result.term == result.normalized_x
    assert result.pulled_at == DATE == result.retrieved_at == result.accessed
    assert [s.gloss for s in result.senses] == [V, P, I, T]
    assert [distinct_sources(s) for s in result.senses] == [2, 2, 1, 1]
    assert [s.wiktionary_sense_no for s in result.senses] == [1, 3, 2, None]
    assert [s.sense_id for s in result.senses] == ["s0", "s1", "s2", "s3"]
    for sense in result.senses:
        sense.check_invariant if hasattr(sense, "check_invariant") else None
        for cite in sense.cites:
            assert cite.source and cite.url and cite.access_date == DATE and cite.license
    result.check_invariant()
    assert result.consensus is result.senses[0]
    assert result.render().startswith("justice:")
    # Panel-b/c sense aliases observe the same votes.
    top = result.senses[0]
    assert top.text == top.gloss
    assert top.citations is top.cites
    assert top.score == top.agreement == 2
    assert set(str(s) for s in top.agrees) == {"wiktionary", "free-dictionary"}
    # Wiktionary pageid evidence flows into the anchor cite.
    assert top.cites[0].pageid == 56878
    assert top.cites[0].url.startswith("https://en.wiktionary.org/")
    assert wiktionary_curid_url(56878) == "https://en.wiktionary.org/?curid=56878"


def test_fused_get_lookup_search_share_cache():
    stub = _stub(
        wik=json_response("wiktionary_justice.json"),
        freed=json_response("freedict_justice.json"),
    )
    chain = _chain(stub)
    first = chain.get("Justice")
    assert chain.lookup("justice") is first
    assert chain.search("  JUSTICE  ") is first
    assert len(stub.calls) == 2
    chain.clear_cache()
    chain.lookup("justice")
    assert len(stub.calls) == 4
    chain.reset_cache()
    assert isinstance(chain, DictionaryChain)


def test_fused_chain_with_helper_and_fake_transport():
    stub = FakeTransport(
        {
            "en.wiktionary.org": json_response("wiktionary_justice.json"),
            "dictionaryapi.dev": json_response("freedict_justice.json"),
        }
    )
    result = chain_with(stub).lookup("justice")
    assert result.state == "ok"
    assert [s.gloss for s in result.senses] == [V, P, I, T]
    assert stub.calls_to("wiktionary") and stub.calls_to("dictionaryapi.dev")


# -- AC2: dictionaryapi 522 still returns Wiktionary senses (2a04fdaa) -------

def test_fused_522_degrades_with_degraded_flag_and_per_source():
    stub = _stub(
        wik=json_response("wiktionary_justice.json"),
        freed=HttpResponse(522, "", ""),
    )
    chain = _chain(stub)
    result = chain.get("justice")
    assert result.state == "ok"
    assert result.degraded is True
    assert [s.gloss for s in result.senses] == [V, I, P]
    # per_source tolerates both hyphen and underscore spellings.
    assert result.per_source["wiktionary"] == "ok"
    assert result.per_source["free-dictionary"] == "unavailable"
    assert result.per_source["free_dictionary"] == "down"  # synonym-equal
    assert result.per_source == {"wiktionary": "ok", "free_dictionary": "down"}
    outcomes = {str(o.source): o for o in result.outcomes}
    assert str(outcomes["wiktionary"].status) == "ok"
    assert outcomes["free-dictionary"].detail == "HTTP 522"
    result.check_invariant()


# -- AC3: explicit empty state, never blank consensus (d708c138) ------------

def test_fused_all_down_is_explicit_empty():
    stub = _stub(wik=TransportError("dns"), freed=HttpResponse(522, "", ""))
    result = _chain(stub).get("justice")
    assert result.state == "empty" and result.status == "empty"
    assert result.is_empty and result.is_empty()  # property + call both work
    assert result.senses == [] and result.consensus is None
    # Canonical reason still compares equal to panel-b/c spellings.
    assert result.empty_reason == "all_sources_unavailable"
    assert result.empty_reason == "all_sources_down"
    assert "all sources unavailable" in result.render().lower()
    result.check_invariant()
    d = result.to_dict()
    assert d["senses"] == [] and d["state"] == "empty"
    assert ChainResult.from_dict(d) == result


def test_fused_no_hit_is_explicit_empty():
    stub = _stub(
        wik=json_response("wiktionary_missing.json"),
        freed=HttpResponse(404, "", ""),
    )
    result = _chain(stub).get("zzzquux")
    assert result.state == "empty"
    assert result.empty_reason == "no_hit"
    assert result.empty_reason == "no_hits"
    assert result.senses == []
    assert result.is_empty()
    result.check_invariant()


def test_fused_punct_only_query_returns_empty_without_network():
    stub = _stub(
        wik=json_response("wiktionary_justice.json"),
        freed=json_response("freedict_justice.json"),
    )
    result = _chain(stub).get("!!!")
    assert result.state == "empty" and result.empty_reason == "no_hit"
    assert stub.calls == []


# -- AC4: virtue and institution stay distinct (0d3ab114) --------------------

def test_fused_virtue_institution_distinct_with_bridge():
    result = consensus(
        "justice",
        DATE,
        [
            SourceResult(SourceOutcome("wiktionary", "ok", None), [
                RawSense(gloss=V, pos="noun", order=1),
                RawSense(gloss=I, pos="noun", order=2),
            ]),
            SourceResult(SourceOutcome("free-dictionary", "ok", None), [
                RawSense(gloss=G, pos="noun", order=1),
            ]),
        ],
    )
    virtue = next(s for s in result.senses if s.gloss == V)
    institution = next(s for s in result.senses if s.gloss == I)
    assert virtue is not institution
    assert [str(c.source) for c in virtue.cites] == ["wiktionary", "free-dictionary"]
    assert [str(c.source) for c in institution.cites] == ["wiktionary"]
    # One vote per (source, sense): the bridge attaches exactly once.
    assert sum(1 for s in result.senses for c in s.cites if str(c.source) == "free-dictionary") == 1


def test_fused_same_source_never_merges_even_identical():
    result = consensus(
        "justice",
        DATE,
        [SourceResult(SourceOutcome("wiktionary", "ok", None), [
            RawSense(gloss=T, pos="verb", order=1),
            RawSense(gloss=T, pos="verb", order=2),
        ])],
    )
    # Within-source exact duplicates collapse to one cite (first wins)...
    assert len(result.senses) == 1
    # ...while distinct same-source wordings never merge even at Jaccard 0.8+.
    close_v = "the fair and honest administration of the law by persons"
    result2 = consensus(
        "justice",
        DATE,
        [SourceResult(SourceOutcome("wiktionary", "ok", None), [
            RawSense(gloss=V, pos="noun", order=1),
            RawSense(gloss=close_v, pos="noun", order=2),
        ])],
    )
    assert len(result2.senses) == 2


def test_fused_cluster_and_rank_senses_keep_distinct():
    wikti = [
        RawSense(gloss=V, pos="noun", order=1, source="wiktionary", url="https://en.wiktionary.org/wiki/justice", license="CC BY-SA 3.0"),
        RawSense(gloss=I, pos="noun", order=2, source="wiktionary", url="https://en.wiktionary.org/wiki/justice", license="CC BY-SA 3.0"),
    ]
    freed = [
        RawSense(gloss=G, pos="noun", order=1, source="free_dictionary", url="https://api.dictionaryapi.dev/api/v2/entries/en/justice", license="unverified-upstream"),
    ]
    clustered = cluster([wikti, freed], DATE, x="justice")
    assert len(clustered) == 2
    assert {s.text for s in clustered} == {V, I}
    ranked = rank_senses(wikti + freed, DATE, x="justice")
    assert {s.gloss for s in ranked} == {V, I, G}
    assert all(s.cites for s in ranked)


# -- Fused compat surface ----------------------------------------------------

def test_fused_normalize_aliases_and_jaccard_shapes():
    assert normalize_x("  JUSTICE  ") == "justice"
    assert normalize_text("  JUSTICE  ") == "justice"
    assert normalize_term("  JUSTICE  ") == "justice"
    assert normalize_key("  Justice!! ") == "justice"
    assert normalize_gloss("  The LAW. ") == "the law."
    assert normalize_sense_text("  The LAW. ") == "the law."
    # tokenize strips trailing punctuation via word regex; gloss_tokens keeps it.
    assert tokenize("Justice is fair.") == frozenset({"justice", "is", "fair"})
    assert gloss_tokens("Justice is fair.") == frozenset({"justice", "is", "fair."})
    assert JACCARD_THRESHOLD == DEDUPE_THRESHOLD == 0.6
    assert jaccard(frozenset({"a"}), frozenset({"a"})) == 1.0
    assert jaccard("justice is fair", "justice is fair") == 1.0
    assert jaccard("aaa bbb", "ccc ddd") == 0.0


def test_fused_status_tables_and_stability():
    assert classify_status(522) == ("down", "http_522")
    assert classify_alias(404) == ("no_hit", "not_found")
    assert classify_status(200) == ("ok", "ok")
    assert stability_for("wiktionary") > stability_for("free-dictionary") > stability_for("merriam-webster")
    assert SOURCES == ("wiktionary", "free-dictionary", "merriam-webster")


def test_fused_transport_http_errors_aliases():
    assert HttpResponse is HttpResponseAlias
    assert issubclass(SourceUnavailable, TransportError)
    assert issubclass(BadSourceResponse, TransportError)
    assert isinstance(StubTransport({}), Transport)
    assert isinstance(UrllibTransport(), Transport)
    assert isinstance(UrllibTransport(), Fetch)
    assert UrlLibFetch is UrllibTransport
    resp = HttpResponse(200, '{"a": 1}', "http://x")
    assert resp.ok and not resp.server_error and resp.json() == {"a": 1}
    assert HttpResponse(500, "", "").server_error
    try:
        HttpResponse(200, "<html>", "").json(source="probe")
        raise AssertionError("expected BadSourceResponse")
    except BadSourceResponse:
        pass


def test_fused_default_sources_excludes_mw_without_key():
    assert [s.name for s in default_sources()] == ["wiktionary", "free-dictionary"]
    keyed = build_default_chain(StubTransport({}), merriam_webster_key="k")
    assert [s.name for s in keyed.sources] == ["wiktionary", "free-dictionary", "merriam-webster"]
    assert keyed.stability_of("wiktionary") == 3


def test_fused_dictionary_is_stdlib_only():
    root = pathlib.Path(__file__).resolve().parent.parent / "dictionary"
    pattern = re.compile(r"^\s*(?:import|from)\s+(requests|httpx|aiohttp|urllib3)\b")
    offenders = [
        f"{path.name}: {line.strip()}"
        for path in sorted(root.glob("*.py"))
        for line in path.read_text(encoding="utf-8").splitlines()
        if pattern.match(line)
    ]
    assert offenders == []


def test_fused_cite_sense_round_trip_with_pageid():
    cite = Cite("wiktionary", "https://en.wiktionary.org/wiki/justice", DATE, "CC BY-SA 3.0", pageid=56878)
    assert cite.accessed == DATE and cite.license_name == "CC BY-SA 3.0"
    assert Cite.from_dict(cite.to_dict()) == cite
    sense = Sense(gloss=V, pos="noun", cites=[cite], wiktionary_sense_no=1, sense_id="s0")
    assert Sense.from_dict(sense.to_dict()) == sense
