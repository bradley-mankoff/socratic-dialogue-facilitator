"""SDF-8 AC2 — the system log is journal-healable.

The log lives in its own fourth file, is read only through
``BoardService.read_system_log``, never appears in ``board_view`` and never
carries chat-voice fields. The journal remains the authority: a settlement
that bypassed the service hook is backfilled on read.
"""

import json
from types import SimpleNamespace

from server.store import (
    GOVERNANCE_OPENED,
    GOVERNANCE_SETTLED,
    SYSTEM_EVENT_TYPES,
)
from tests.sdf5_stubs import JUSTICE, THRASYMACHUS, make_service

HANDLES = ("Cephalus", "Polemarchus", "Thrasymachus", "Cleitophon")
VOTERS = ("Cephalus", "Polemarchus", "Thrasymachus")


def governance_board(root, *, humans=HANDLES, claim=True):
    svc = make_service(root)
    opened = svc.open_board(JUSTICE, pull_canonicals=False)
    board_id = opened.board_id
    machine = svc.machine(board_id)
    h = {name: machine.enroll_handle(name) for name in humans}
    if claim:
        svc.claim_original(board_id, THRASYMACHUS,
                           claimant_display=humans[0])
    return SimpleNamespace(service=svc, board_id=board_id, machine=machine,
                           h=h)


def _vote(svc, env, q_id, side):
    for name in VOTERS:
        svc.cast_vote(env.board_id, q_id, side, handle_id=env.h[name])


def _scan_for_system_entries(node):
    """Fail on any log marker anywhere in a view payload."""
    if isinstance(node, dict):
        assert "origin" not in node
        for key, value in node.items():
            assert key not in SYSTEM_EVENT_TYPES
            _scan_for_system_entries(value)
    elif isinstance(node, list):
        for item in node:
            _scan_for_system_entries(item)
    elif isinstance(node, str):
        assert node not in SYSTEM_EVENT_TYPES


def test_system_log_never_in_board_view(tmp_path):
    env = governance_board(tmp_path)
    svc, bid = env.service, env.board_id
    q1 = svc.propose_ingress_selection(bid, "candidate-a",
                                       opened_by=env.h["Cephalus"])
    _vote(svc, env, q1, "for")
    q2 = svc.propose_ingress_selection(bid, "candidate-b",
                                       opened_by=env.h["Cephalus"])
    _vote(svc, env, q2, "for")

    # read-ins order: each opened entry before its settled entry
    entries = svc.read_system_log(bid)
    assert [e["type"] for e in entries] == [
        GOVERNANCE_OPENED, GOVERNANCE_SETTLED,
        GOVERNANCE_OPENED, GOVERNANCE_SETTLED,
    ]
    assert [e["payload"]["q_id"] for e in entries[::2]] == [q1, q2]
    assert len(svc.read_system_log(bid, GOVERNANCE_OPENED)) == 2
    assert len(svc.read_system_log(bid, GOVERNANCE_SETTLED)) == 2

    blob = json.dumps(svc.view(bid))
    assert "governance_opened" not in blob
    assert "governance_settled" not in blob
    _scan_for_system_entries(svc.view(bid))


def test_system_entries_carry_ids_not_voice(tmp_path):
    env = governance_board(tmp_path)
    svc, bid, m = env.service, env.board_id, env.machine
    q = svc.propose_ingress_selection(bid, "candidate-a",
                                      opened_by=env.h["Cephalus"])
    _vote(svc, env, q, "for")
    ingress = svc.propose_ingress_selection(bid, "voiceprint-enrollment",
                                            opened_by=env.h["Cephalus"])
    _vote(svc, env, ingress, "for")

    entries = svc.read_system_log(bid)
    assert entries
    allowed = {
        "q_id", "kind", "subject", "outcome", "tally", "census_size",
        "settled_seq", "opened_seq", "opened_by", "carried_unresolved",
        "closed_seq", "origin",
    }
    banned = {"text", "display", "reason", "ballots", "claimed_by"}
    for event in entries:
        assert event["type"] in SYSTEM_EVENT_TYPES
        payload = event["payload"]
        assert payload["origin"] == "system"
        assert set(payload) <= allowed
        assert not (set(payload) & banned)
        if payload.get("opened_by") is not None:
            assert payload["opened_by"] in m.state.handles

    blob = json.dumps([e["payload"] for e in entries])
    assert THRASYMACHUS not in blob
    for display in ("Cephalus", "Polemarchus", "Thrasymachus",
                    "Cleitophon"):
        assert display not in blob


def test_escape_hatch_heals_on_read(tmp_path):
    env = governance_board(tmp_path)
    svc, bid, m = env.service, env.board_id, env.machine
    q = svc.propose_ingress_selection(bid, "cand",
                                      opened_by=env.h["Cephalus"])
    # a direct machine vote bypasses the service settlement hook entirely
    m.cast(q, env.h["Cephalus"], "explicit", "for")
    m.cast(q, env.h["Polemarchus"], "explicit", "for")
    m.cast(q, env.h["Thrasymachus"], "explicit", "for")
    assert m.q_status(q) == ("settled", "for")
    assert svc.system.read_events(bid, GOVERNANCE_SETTLED) == []

    healed = svc.read_system_log(bid)
    assert [e["type"] for e in healed] == [GOVERNANCE_OPENED,
                                           GOVERNANCE_SETTLED]
    row = healed[-1]["payload"]
    assert row["q_id"] == q
    assert row["outcome"] == "for"
    assert row["tally"] == {"for": 3, "against": 0}

    # deleting the projection cannot lose history: the journal rebuilds it
    # with the same payload builders, byte-identical in shape
    path = svc.system.path_for(bid)
    assert path.exists()
    path.unlink()
    rebuilt = svc.read_system_log(bid)
    assert [(e["type"], e["payload"]) for e in rebuilt] == \
        [(e["type"], e["payload"]) for e in healed]
