"""Pure consensus merging (SDF-3): ranking, vote attachment, empty state."""

from dictionary.chain import SourceResult, consensus, distinct_sources
from dictionary.model import SOURCES, SourceOutcome
from dictionary.sources import RawSense

DATE = "2026-09-13"

V = "The fair and honest administration of the law by individuals."
I = "The fair and honest administration of the law by courts."
P = "A judge of a court of law."
G = "The fair and honest administration of the law."
G2 = "A judge of a court of law."
T = "To punish a person appropriately for an offense."


def _result(source, status="ok", glosses=(), detail=None, pos="noun"):
    senses = [
        RawSense(gloss=gloss, pos=pos, order=index + 1)
        for index, gloss in enumerate(glosses)
    ]
    return SourceResult(SourceOutcome(source, status, detail), senses)


def _wik(*glosses):
    return _result("wiktionary", "ok", glosses)


def _fd(*glosses):
    return _result("free-dictionary", "ok", glosses)


def _down(source, detail="HTTP 522"):
    return _result(source, "unavailable", (), detail)


def _miss(source):
    return _result(source, "no_entry", ())


def _assert_no_blank_strings(value):
    if isinstance(value, dict):
        for child in value.values():
            _assert_no_blank_strings(child)
    elif isinstance(value, list):
        for child in value:
            _assert_no_blank_strings(child)
    elif isinstance(value, str):
        assert value != ""


def test_full_convergence_ranks_corroborated_sense_first():
    result = consensus("justice", DATE, [_wik(V, I, P), _fd(G, G2, T)])
    assert result.x == "justice"
    assert result.state == "ok"
    assert result.empty_reason is None
    assert [s.gloss for s in result.senses] == [V, P, I, T]
    assert [distinct_sources(s) for s in result.senses] == [2, 2, 1, 1]
    assert [s.wiktionary_sense_no for s in result.senses] == [1, 3, 2, None]


def test_every_sense_carries_complete_cite_record():
    result = consensus("justice", DATE, [_wik(V, I, P), _fd(G, G2, T)])
    assert result.pulled_at == DATE
    assert result.x == "justice"
    for sense in result.senses:
        assert sense.cites, sense.gloss
        for cite in sense.cites:
            assert cite.source in SOURCES
            assert cite.url
            assert cite.access_date == result.pulled_at
            assert cite.license


def test_virtue_and_institution_senses_stay_distinct_under_bridge():
    result = consensus("justice", DATE, [_wik(V, I, P), _fd(G, T)])
    assert len(result.senses) == 4
    wik_senses = [s for s in result.senses if s.wiktionary_sense_no is not None]
    assert len(wik_senses) == 3
    assert {s.wiktionary_sense_no for s in wik_senses} == {1, 2, 3}
    virtue = next(s for s in result.senses if s.gloss == V)
    institution = next(s for s in result.senses if s.gloss == I)
    assert virtue is not institution
    assert virtue.gloss != institution.gloss
    assert [c.source for c in virtue.cites] == ["wiktionary", "free-dictionary"]
    assert [c.source for c in institution.cites] == ["wiktionary"]
    standalone = next(s for s in result.senses if s.gloss == T)
    assert standalone.wiktionary_sense_no is None


def test_bridge_gloss_attaches_to_single_best_match():
    result = consensus("justice", DATE, [_wik(V, I), _fd(G)])
    fd_cites = [
        cite
        for sense in result.senses
        for cite in sense.cites
        if cite.source == "free-dictionary"
    ]
    assert len(fd_cites) == 1
    virtue = next(s for s in result.senses if s.gloss == V)
    institution = next(s for s in result.senses if s.gloss == I)
    assert [c.source for c in virtue.cites] == ["wiktionary", "free-dictionary"]
    assert [c.source for c in institution.cites] == ["wiktionary"]
    for sense in result.senses:
        sources = [c.source for c in sense.cites]
        assert sources.count("free-dictionary") <= 1


def test_exact_duplicate_secondary_gloss_collapses():
    result = consensus("justice", DATE, [_fd(T, T)])
    assert len(result.senses) == 1
    assert result.senses[0].gloss == T
    assert distinct_sources(result.senses[0]) == 1
    assert len(result.senses[0].cites) == 1


def test_all_sources_unavailable_yields_empty_all_down():
    result = consensus(
        "justice",
        DATE,
        [
            _down("wiktionary", "TransportError: dns"),
            _down("free-dictionary", "HTTP 522"),
        ],
    )
    assert result.state == "empty"
    assert result.is_empty()
    assert result.senses == []
    assert result.empty_reason == "all_sources_unavailable"
    assert [o.status for o in result.outcomes] == ["unavailable", "unavailable"]
    _assert_no_blank_strings(result.to_dict())


def test_no_hit_and_mixed_yield_empty_no_hit():
    cases = [
        ([_miss("wiktionary"), _miss("free-dictionary")], "no_hit"),
        ([_miss("wiktionary"), _down("free-dictionary")], "no_hit"),
        ([_down("wiktionary"), _miss("free-dictionary")], "no_hit"),
        ([_result("wiktionary", "ok", ()), _miss("free-dictionary")], "no_hit"),
    ]
    for results, reason in cases:
        result = consensus("zzzquux", DATE, results)
        assert result.state == "empty"
        assert result.empty_reason == reason
        assert result.senses == []
        assert result.is_empty()
    all_down = consensus(
        "zzzquux", DATE, [_down("wiktionary"), _down("free-dictionary")]
    )
    assert all_down.empty_reason == "all_sources_unavailable"
