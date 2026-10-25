"""Stories 15–21 in one line: the Justice fixture walked through the
service's scrutiny API, plus durability across a reopen.

Thrasymachus claims; Cephalus alleges the 3a erring-ruler; ambient and
explicit ballots dedupe to one counted ballot each; the tie stands
not-refuted; re-calls flip refuted/un-refuted; the scoreboard matches the
machine; ``revise`` freezes the question and hands SDF-7 a correct tray.
Then durability: the whole journal replays byte-identical after a reopen.
"""

import json

import board.verdicts as V
from board.machine import fold_events
from server.model import CLAIM_RECORDED, VOTE_EVENT_TYPES
from tests.sdf5_stubs import empty_chain, make_service
from tests.sdf6_stubs import make_svc


def test_erring_ruler_refutes_and_unrefutes_through_the_service(tmp_path):
    env = make_svc(tmp_path, label="sdf6-justice", allege=False)
    service, bid, machine = env.service, env.board_id, env.machine
    cephalus, polemarchus, thrasymachus = (
        env.h["Cephalus"], env.h["Polemarchus"], env.h["Thrasymachus"])

    # story 15 — Cephalus alleges the erring ruler against the claim
    alleged = service.allege(bid, "3a", by_display="Cephalus")
    assert alleged.node_id == env.node and alleged.shape == "3a"
    ref_q = alleged.q_id
    state = machine.state
    assert state.ces[alleged.ce_id].shape == "3a"
    assert state.questions[ref_q].opened_by == cephalus

    # stories 16–17 — ambient + explicit ballots, one counted per person
    first = service.record_ambient_vote(bid, ref_q, "stands",
                                        by_display="Polemarchus",
                                        receive_time=1.0)
    shadow = service.record_ambient_vote(bid, ref_q, "stands",
                                         by_display="Thrasymachus",
                                         receive_time=1.5)
    explicit = service.cast_vote(bid, ref_q, "rebutted",
                                 by_display="Thrasymachus",
                                 reason="Socrates rebutted the example")
    counted = V.counted(machine.state, ref_q)
    assert set(counted) == {polemarchus, thrasymachus}, \
        "one counted ballot per person; the alleger has not voted"
    assert counted[thrasymachus].ballot_id == explicit.ballot_id, \
        "explicit precedence: the ambient shadow is superseded"
    assert explicit.replaced_ballot_id == shadow.ballot_id
    assert explicit.counted is True

    # story 18 — the 1–1 tie stands not-refuted (live predicate, no settle)
    assert machine.standing_counts(alleged.ce_id) == (1, 1)
    assert machine.is_refuted(alleged.ce_id) is False
    assert machine.q_status(ref_q) == ("open", None)
    assert state.nodes[env.node].status == "unrefuted"

    # story 19 — the live scoreboard mirrors the machine exactly
    sb = service.scoreboard(bid)
    assert sb["is_refuted"] is False
    row = sb["ces"][0]
    assert row["tally"] == {"stands": 1, "rebutted": 1}
    assert row["census_size"] == len(machine.census(ref_q)) == 3
    assert [(v["display"], v["is_counted"]) for v in row["votes"]] == [
        ("Polemarchus", True), ("Thrasymachus", False),
        ("Thrasymachus", True)]
    assert json.loads(json.dumps(sb)) == sb

    # story 18 again — re-calls flip the live verdict both ways: Cephalus
    # joins the stands side (refuted), Polemarchus re-calls (un-refuted),
    # Thrasymachus re-calls (refuted) — only the latest ballot counts
    flipped = service.cast_vote(bid, ref_q, "stands", handle_id=cephalus)
    assert flipped.refuted is True, "2 stands over census 3 refutes"
    assert flipped.replaced_ballot_id is None, "Cephalus had nothing counted"
    assert machine.state.nodes[env.node].status == "refuted"
    unflipped = service.cast_vote(bid, ref_q, "rebutted",
                                  handle_id=polemarchus,
                                  reason="on reflection, the example holds")
    assert unflipped.refuted is False
    assert machine.state.nodes[env.node].status == "unrefuted"
    assert unflipped.replaced_ballot_id == first.ballot_id, \
        "the superseded ballot is Polemarchus' own counted ambient"
    back = service.cast_vote(bid, ref_q, "stands", handle_id=thrasymachus,
                             reason="the ruler errs after all")
    assert back.refuted is True
    assert machine.counted(ref_q, thrasymachus).side == "stands"

    # story 21 — the vote feed is journal-sourced, only vote events, ordered
    events = service.vote_events(bid)
    assert all(e["type"] in VOTE_EVENT_TYPES for e in events)
    assert [e["seq"] for e in events] == sorted(e["seq"] for e in events)
    assert json.loads(json.dumps(events)) == events
    assert len([e for e in events if e["type"] == "retraction"]) == 0
    # the sidecar never heard about any of this
    assert [e["type"] for e in service.meta.read_events(bid)] == [
        CLAIM_RECORDED]

    # SDF-5 interplay — revise in response: the open Q freezes, tray correct
    revised = service.revise(bid, "Justice is teaching what is good.",
                             claimant_display="Thrasymachus",
                             in_response_to=alleged.ce_id)
    assert ref_q in revised.frozen_q_ids
    state = machine.state
    assert state.questions[ref_q].status == "frozen"
    assert state.active_node_id == revised.node_id
    tray = revised.revision_event["payload"]
    carried = [r for r in tray["unresolved_ces"] if r["carried"]]
    assert [r["ce_id"] for r in carried] == [alleged.ce_id], \
        "the standing CE is the one carried, outcome recorded"
    assert carried[0]["outcome"] == "stands"

    # post-revision: the fresh active claim takes new allegations (3b on n2)
    fresh = service.allege(bid, "3b")
    assert fresh.node_id == revised.node_id
    voted2 = service.cast_vote(bid, fresh.q_id, "stands",
                               by_display="Glaucon")
    assert voted2.counted is True
    assert machine.state.nodes[revised.node_id].status == "unrefuted"
    del first, shadow, voted2, back


def test_justice_votes_and_durability(tmp_path):
    env = make_svc(tmp_path, label="sdf6-horn", allege=False)
    service, bid, machine = env.service, env.board_id, env.machine
    cephalus, polemarchus, thrasymachus = (
        env.h["Cephalus"], env.h["Polemarchus"], env.h["Thrasymachus"])

    alleged = service.allege(bid, "3a", by_display="Cephalus")
    ref_q = alleged.q_id
    # 1–1 tie on the CE's refutation Q (census: the three handles)
    service.cast_vote(bid, ref_q, "stands", by_display="Polemarchus")
    service.cast_vote(bid, ref_q, "rebutted", by_display="Thrasymachus")
    assert machine.is_standing(alleged.ce_id) is True
    assert machine.is_refuted(alleged.ce_id) is False

    # the verdict is a live predicate: refutation Qs never settle
    assert machine.q_status(ref_q) == ("open", None), \
        "refutation Qs never settle; the verdict is a live predicate"

    # story 21 — the whole vote sequence, in journal order
    events = service.vote_events(bid)
    assert [e["type"] for e in events] == [
        "ballot_cast", "ballot_cast",                    # refutation 1–1
    ]
    assert all(e["type"] in VOTE_EVENT_TYPES for e in events)

    # story 19 — scoreboard, before reopening
    sb = service.scoreboard(bid)
    assert sb["ces"][0]["tally"] == {"stands": 1, "rebutted": 1}

    # durability — reopen the same data root and compare everything
    state = machine.state
    reopened = make_service(tmp_path, chain=empty_chain())
    assert reopened.state(bid) == state
    assert reopened.scoreboard(bid) == sb
    assert reopened.vote_events(bid) == events
    assert reopened.view(bid) == service.view(bid)
    assert fold_events(reopened.journals.read_all(bid)) == state
    assert [e["type"] for e in reopened.meta.read_events(bid)] == [
        CLAIM_RECORDED]
