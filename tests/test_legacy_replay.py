"""Legacy replay — journals written before the sdf-zj6.1 cut still open.

Symposiums started on the pull-request-#26 code hold ``socrates_set``,
``mode_switch_applied``, ``tiebreak_ballot_cast``, ``active_switch_applied``
and ``defense_cede_*`` events in their journals. Replaying them must not
raise: the cut drops those types, so the fold skips them and the board
still opens with its people, claims and votes intact.
"""

from board.machine import fold_events


def _seq(events):
    return [{"seq": i + 1, "type": t, "payload": p, "ts": "2026-10-25T00:00:00+00:00"}
            for i, (t, p) in enumerate(events)]


def test_pr26_journal_with_dropped_events_replays():
    events = _seq([
        ("board_created", {"board_id": "b1", "x_title": "Justice",
                           "medium": "async"}),
        ("handle_enrolled", {"handle_id": "h1", "display": "Ada",
                            "kind": "enrolled"}),
        ("handle_enrolled", {"handle_id": "h2", "display": "Bohdan",
                            "kind": "enrolled"}),
        # dropped by the cut: the Socrates seat, a mode switch, a cede
        # offer/accept pair, an active-claim switch and a tiebreak ballot
        ("socrates_set", {"handle_id": "h1"}),
        ("mode_switch_applied", {"mode": "facilitates",
                                 "withdrawn_ballot_ids": []}),
        ("node_registered", {"node_id": "n1", "text": "Justice is order.",
                             "version": 1, "prev_active_node_id": None,
                             "defender": "h1"}),
        ("defense_cede_offered", {"from": "h1", "to": "h2",
                                  "node_id": "n1"}),
        ("defense_cede_accepted", {"from": "h1", "to": "h2",
                                   "node_id": "n1"}),
        ("active_switch_applied", {"node_id": "n1",
                                   "prev_active_node_id": None}),
        ("q_opened", {"q_id": "q1", "kind": "refutation", "subject": "ce1",
                      "node_id": "n1", "ce_id": "ce1", "shape": "3a",
                      "opened_by": "h1", "roster": ["h1", "h2"]}),
        ("tiebreak_ballot_cast", {"ballot_id": "b0", "q_id": "q1",
                                  "handle_id": "h1", "ce_id": "ce1",
                                  "reason": "stays so",
                                  "receive_time": 1.0}),
        ("ballot_cast", {"ballot_id": "b1", "q_id": "q1", "handle_id": "h1",
                         "channel": "explicit", "side": "stands",
                         "reason": None, "labeled": False,
                         "receive_time": 2.0}),
    ])
    state = fold_events(events)
    assert state.board_id == "b1"
    assert sorted(state.handles) == ["h1", "h2"]
    assert state.active_node_id == "n1"
    assert state.seq == len(events)
