"""Chain data shape round-trips and stable vocab (SDF-3)."""

from dictionary.model import (
    CHAIN_STATES,
    EMPTY_REASONS,
    PRIMARY,
    SOURCES,
    SOURCE_STATUSES,
    ChainResult,
    Cite,
    Sense,
    SourceOutcome,
)


def test_vocabulary_tuples_are_stable():
    assert SOURCES == ("wiktionary", "free-dictionary", "merriam-webster")
    assert SOURCE_STATUSES == ("ok", "no_entry", "unavailable")
    assert CHAIN_STATES == ("ok", "empty")
    assert EMPTY_REASONS == ("all_sources_unavailable", "no_hit")
    assert PRIMARY == "wiktionary"


def _cite(source="wiktionary", **overrides):
    base = dict(
        source=source,
        url="https://en.wiktionary.org/wiki/justice",
        access_date="2026-09-13",
        license="CC BY-SA 3.0",
        raw=None,
    )
    base.update(overrides)
    return Cite(**base)


def test_cite_round_trip():
    cite = _cite()
    assert Cite.from_dict(cite.to_dict()) == cite
    with_raw = _cite(raw={"pageid": 56878})
    assert Cite.from_dict(with_raw.to_dict()) == with_raw


def test_sense_round_trip_with_nested_cites():
    sense = Sense(
        gloss="The fair and honest administration of the law by individuals.",
        pos="noun",
        cites=[
            _cite(),
            _cite(
                source="free-dictionary",
                url="https://api.dictionaryapi.dev/api/v2/entries/en/justice",
                license="unverified-upstream",
            ),
        ],
        wiktionary_sense_no=1,
    )
    rebuilt = Sense.from_dict(sense.to_dict())
    assert rebuilt == sense
    assert [type(cite) for cite in rebuilt.cites] == [Cite, Cite]


def test_source_outcome_round_trip():
    ok = SourceOutcome("wiktionary", "ok", None)
    down = SourceOutcome("free-dictionary", "unavailable", "HTTP 522")
    miss = SourceOutcome("wiktionary", "no_entry", None)
    for outcome in (ok, down, miss):
        assert SourceOutcome.from_dict(outcome.to_dict()) == outcome


def test_chain_result_round_trip_including_empty_factory():
    outcomes = [
        SourceOutcome("wiktionary", "unavailable", "TransportError: dns"),
        SourceOutcome("free-dictionary", "unavailable", "HTTP 522"),
    ]
    empty = ChainResult.empty(
        "justice", "all_sources_unavailable", outcomes, "2026-09-13"
    )
    assert empty.is_empty()
    assert empty.senses == []
    assert empty.empty_reason == "all_sources_unavailable"
    assert ChainResult.from_dict(empty.to_dict()) == empty

    sense = Sense(
        gloss="A judge of a court of law.",
        pos="noun",
        cites=[_cite()],
        wiktionary_sense_no=3,
    )
    ok = ChainResult(
        x="justice",
        state="ok",
        senses=[sense],
        empty_reason=None,
        outcomes=[SourceOutcome("wiktionary", "ok", None)],
        pulled_at="2026-09-13",
    )
    assert not ok.is_empty()
    assert ChainResult.from_dict(ok.to_dict()) == ok
