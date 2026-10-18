"""SDF-14 — ambient tally via fixtures (spec stories 18, 19).

Seam: ``voice.tally.AmbientTally`` (pure, headless, stdlib only).
Transcript/timing fixtures drive ambient vote events: confirmed
:class:`TranscriptSegment` values (the SDF-11 capture output) flow through
an injected brain classifier into ambient ballots on the verdict machine.
The machine's counted-ballot predicates do the deduping — latest explicit
wins over any ambient, one counted ballot per speaker, retractions touch
ambient only — so the tally stays a thin wire: classify, record, retract.
"""

from __future__ import annotations

import pytest

from voice.capture import TranscriptSegment


class FixtureClassifier:
    """Stub brain: canned text -> side, unknown text abstains (no ballot).

    Stands in for the hosted/local model behind the same ``classify``
    seam; the Mac qualification path (SDF-20) swaps the real model in.
    """

    def __init__(self, votes: dict[str, str]):
        self.votes = dict(votes)

    def classify(self, text: str) -> str | None:
        return self.votes.get(text)


def make_board():
    from board.machine import VerdictMachine

    m = VerdictMachine.in_memory()
    h = {name: m.enroll_handle(name) for name in ("a", "b", "c")}
    n = m.register_node("n1", "Justice is the advantage of the stronger.")
    ce, q = m.open_refutation_q(n, "3a", opened_by=h["a"])
    return m, h, ce, q


def seg(text: str, confirmed_at: float) -> TranscriptSegment:
    return TranscriptSegment(text=text, start_t=confirmed_at - 0.6,
                             end_t=confirmed_at - 0.1,
                             confirmed_at=confirmed_at)


def test_late_ambient_after_explicit_keeps_explicit_ballot():
    from voice.tally import AmbientTally

    m, h, ce, q = make_board()
    tally = AmbientTally(m, FixtureClassifier({"late second thoughts": "stands"}))
    m.cast(q, h["a"], "explicit", "rebutted", receive_time=1.0)
    # timing fixture: ambient hypothesis confirms LATER but must still lose
    ballot_id = tally.observe_segment(seg("late second thoughts", 9.0),
                                      q_id=q, handle_id=h["a"])
    assert ballot_id is not None
    assert m.counted(q, h["a"]).side == "rebutted"
    assert m.counted(q, h["a"]).channel == "explicit"


def test_same_speaker_twice_yields_one_counted_ballot():
    from voice.tally import AmbientTally

    m, h, ce, q = make_board()
    tally = AmbientTally(m, FixtureClassifier({"it stands": "stands",
                                              "no it falls": "rebutted"}))
    tally.observe_segment(seg("it stands", 1.0), q_id=q, handle_id=h["a"])
    tally.observe_segment(seg("no it falls", 2.0), q_id=q, handle_id=h["a"])
    # dedupe-by-speaker: two ambient events, one counted ballot, latest wins
    assert m.counted(q, h["a"]).side == "rebutted"
    assert m.standing_counts(ce) == (0, 1)


def test_classifier_retraction_never_demotes_explicit():
    from voice.tally import AmbientTally

    m, h, ce, q = make_board()
    tally = AmbientTally(m, FixtureClassifier({"it stands": "stands"}))
    m.cast(q, h["a"], "explicit", "rebutted", receive_time=1.0)
    tally.observe_segment(seg("it stands", 2.0), q_id=q, handle_id=h["a"])
    # the brain takes back its ambient hypothesis; the explicit stands
    tally.retract(q, h["a"])
    counted = m.counted(q, h["a"])
    assert counted.side == "rebutted"
    assert counted.channel == "explicit"


def test_classifier_abstention_records_no_ballot():
    from voice.tally import AmbientTally

    m, h, ce, q = make_board()
    tally = AmbientTally(m, FixtureClassifier({}))
    assert tally.observe_segment(seg("what did we have for lunch", 1.0),
                                 q_id=q, handle_id=h["a"]) is None
    assert m.counted(q, h["a"]) is None
