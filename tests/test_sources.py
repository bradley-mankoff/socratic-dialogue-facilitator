"""Source parsing + fetch outcomes over stubbed HTTP (SDF-3 story 8)."""

import json

from dictionary.model import SourceOutcome
from dictionary.sources import (
    FreeDictionarySource,
    MerriamWebsterSource,
    WiktionarySource,
    parse_wikitext_senses,
)
from dictionary.transport import HttpResponse
from tests.stubs import StubTransport, json_response, load_fixture

V = "The fair and honest administration of the law by individuals."
I = "The fair and honest administration of the law by courts."
P = "A judge of a court of law."
G = "The fair and honest administration of the law."
G2 = "A judge of a court of law."
T = "To punish a person appropriately for an offense."


def _wikitext():
    data = load_fixture("wiktionary_justice.json")
    return data["query"]["pages"]["56878"]["revisions"][0]["slots"]["main"]["*"]


def test_wiktionary_parses_three_noun_senses_in_order():
    senses = parse_wikitext_senses(_wikitext())
    assert [s.gloss for s in senses] == [V, I, P]
    assert [s.order for s in senses] == [1, 2, 3]
    assert all(s.pos == "noun" for s in senses)


def test_wiktionary_strips_templates_and_skips_quotes():
    for sense in parse_wikitext_senses(_wikitext()):
        assert "{{" not in sense.gloss and "}}" not in sense.gloss
        assert "<ref" not in sense.gloss
        assert "quote-book" not in sense.gloss
        assert "quote context" not in sense.gloss


def test_wiktionary_excludes_non_english_sections():
    wikitext = (
        "==English==\n===Noun===\n"
        "# The fair and honest administration of the law.\n"
        "==German==\n===Noun===\n# Gerechtigkeit\n"
    )
    senses = parse_wikitext_senses(wikitext)
    assert [s.gloss for s in senses] == [G]


def test_wiktionary_multi_pos_headers_tracked():
    wikitext = (
        "==English==\n===Noun===\n# One.\n"
        "====Quotations====\n# Two.\n"
        "===Verb===\n# Three.\n"
    )
    senses = parse_wikitext_senses(wikitext)
    assert [s.gloss for s in senses] == ["One.", "Two.", "Three."]
    assert [s.pos for s in senses] == ["noun", None, "verb"]
    assert [s.order for s in senses] == [1, 2, 3]


def test_wiktionary_missing_page_yields_no_entry_outcome():
    stub = StubTransport(
        {"en.wiktionary.org": json_response("wiktionary_missing.json")}
    )
    senses, outcome = WiktionarySource().fetch("zzzquux", stub)
    assert senses == []
    assert outcome == SourceOutcome("wiktionary", "no_entry", None)
    assert "titles=zzzquux" in stub.calls[0]


def test_freedictionary_parses_definitions_with_pos():
    stub = StubTransport(
        {"dictionaryapi.dev": json_response("freedict_justice.json")}
    )
    senses, outcome = FreeDictionarySource().fetch("justice", stub)
    assert isinstance(outcome, SourceOutcome)
    assert outcome.status == "ok"
    assert [s.gloss for s in senses] == [G, G2, T]
    assert [s.pos for s in senses] == ["noun", "noun", "verb"]
    assert [s.order for s in senses] == [1, 2, 3]


def test_freedictionary_404_yields_no_entry_outcome():
    stub = StubTransport({"dictionaryapi.dev": HttpResponse(404, "", "")})
    senses, outcome = FreeDictionarySource().fetch("zzzquux", stub)
    assert senses == []
    assert outcome.status == "no_entry"


def test_freedictionary_malformed_payload_yields_unavailable():
    non_json = StubTransport(
        {"dictionaryapi.dev": HttpResponse(200, "<html>nope", "")}
    )
    senses, outcome = FreeDictionarySource().fetch("justice", non_json)
    assert senses == []
    assert outcome.status == "unavailable"
    assert outcome.detail == "invalid JSON"

    wrong_shape = StubTransport(
        {
            "dictionaryapi.dev": HttpResponse(
                200, json.dumps({"word": "justice"}), ""
            )
        }
    )
    senses, outcome = FreeDictionarySource().fetch("justice", wrong_shape)
    assert senses == []
    assert outcome.status == "unavailable"
    assert outcome.detail == "invalid JSON"


def test_merriam_webster_parses_shortdef_and_miss_yields_no_entry():
    source = MerriamWebsterSource("test-key")
    stub = StubTransport(
        {"dictionaryapi.com": json_response("merriam_justice.json")}
    )
    senses, outcome = source.fetch("justice", stub)
    assert outcome.status == "ok"
    assert len(senses) == 1
    assert senses[0].gloss == P
    assert senses[0].pos == "noun"
    assert "{bc}" not in senses[0].gloss

    suggestion = StubTransport(
        {"dictionaryapi.com": HttpResponse(200, json.dumps(["justice", "just"]), "")}
    )
    senses, outcome = source.fetch("justice", suggestion)
    assert senses == []
    assert outcome.status == "no_entry"


def test_stability_weights_rank_wiktionary_first():
    from dictionary.sources import stability_for
    assert stability_for("wiktionary") > stability_for("free-dictionary") > stability_for("merriam-webster")
