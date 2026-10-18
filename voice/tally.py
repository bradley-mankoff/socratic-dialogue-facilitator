"""SDF-14 — ambient tally via fixtures (spec stories 18, 19).

Thin headless wire from confirmed transcript segments (the SDF-11 capture
output) through the brain classifier into ambient ballots. The verdict
machine owns every counting predicate — latest explicit beats any ambient,
one counted ballot per speaker, retractions touch ambient only — so this
module classifies, records, and retracts, and nothing more.

Timing is a fixture input: :meth:`AmbientTally.observe_segment` stamps the
ambient ballot with the segment's ``confirmed_at`` as its receive time, so
transcript/timing fixtures (including explicit-beats-late-ambient) drive
the same ordering the server uses live.
"""

from __future__ import annotations

from typing import Protocol

SIDES: tuple[str, ...] = ("stands", "rebutted")


class BrainClassifier(Protocol):
    """Brain seam (hosted API default, local-model path in production,
    canned text->side map in fixtures). Returns the ambient side, or
    None to abstain when the utterance carries no vote."""

    def classify(self, text: str) -> str | None: ...


class AmbientTally:
    """Classify confirmed segments into ambient ballots on one machine."""

    def __init__(self, machine, classifier: BrainClassifier) -> None:
        self._machine = machine
        self._classifier = classifier

    def observe(self, q_id: str, handle_id: str, text: str,
                receive_time: float | None = None) -> str | None:
        """Classify one utterance; record the ambient ballot it votes.

        Returns the ballot id, or None when the classifier abstains."""
        side = self._classifier.classify(text)
        if side is None:
            return None
        if side not in SIDES:
            raise ValueError(f"classifier side must be one of {SIDES}")
        return self._machine.record_ambient(q_id, handle_id, side,
                                            receive_time=receive_time)

    def observe_segment(self, segment, q_id: str,
                        handle_id: str) -> str | None:
        """Classify one confirmed segment, stamped at its confirm time."""
        return self.observe(q_id, handle_id, segment.text,
                            receive_time=segment.confirmed_at)

    def retract(self, q_id: str, handle_id: str) -> None:
        """Withdraw the counted ambient ballot (classifier self-correction).

        Ambient-layer only: the machine no-ops when the counted ballot is
        explicit, so a retraction can never demote an explicit ballot."""
        self._machine.retract(q_id, handle_id)


__all__ = ["SIDES", "BrainClassifier", "AmbientTally"]
