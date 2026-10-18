"""AC4 — every mutation persists; reload reconstructs identical state."""

from board.machine import VerdictMachine
from board.store import JsonlStore
from board.verdicts import census, governance_passed, is_refuted


def _scripted_board(store):
    """The §8 scripted scenario: enrolls, node, 2 CEs (1 attached), mixed
    ambient+explicit casts, re-vote, medium toggle, mode switches,
    tiebreak, close."""
    m = VerdictMachine(store, "b1")
    m.create_board("b1", "Justice (Republic Book I)", "participates", "async")
    h1 = m.enroll_handle("h1")
    h2 = m.enroll_handle("h2")
    h3 = m.enroll_handle("h3")
    f1 = m.enroll_handle("facilitator", is_facilitator=True)
    n1 = m.register_node("n1", "Justice is the advantage of the stronger.")
    ce1, q1 = m.open_refutation_q(n1, "3a", opened_by=h1)
    m.cast(q1, h1, "explicit", "stands")
    m.cast(q1, h2, "explicit", "stands")
    m.record_ambient(q1, f1, "stands")
    m.record_ambient(q1, h3, "rebutted")
    m.cast(q1, h1, "explicit", "rebutted")          # re-vote
    m.toggle_medium("live")
    m.set_socrates(h1)
    q2 = m.open_governance_q("mode_switch", subject="facilitates",
                             opened_by=h1)
    for who in (h1, h2, h3):
        m.cast(q2, who, "explicit", "for")
    q3 = m.open_governance_q("mode_switch", subject="participates",
                             opened_by=h1)
    for who in (h1, h2):
        m.cast(q3, who, "explicit", "for")
    m.cast(q1, f1, "explicit", "stands")            # re-eligible ballot
    q4 = m.open_governance_q("mode_switch", subject="facilitates",
                             opened_by=h1)
    for who in (h1, h2, h3):
        m.cast(q4, who, "explicit", "for")
    q5 = m.open_governance_q("tiebreak", subject=ce1, opened_by=h1)
    for who in (h1, h2):
        m.cast(q5, who, "explicit", "for")
    m.tiebreak_ballot(ce1, "the example misapplies the definition")
    qc = m.open_governance_q("close", opened_by=h1)
    for who in (h1, h2):
        m.cast(qc, who, "explicit", "for")
    return m, dict(h1=h1, h2=h2, h3=h3, f1=f1, n1=n1, ce1=ce1, q1=q1)


def test_reload_after_every_mutation(tmp_path):
    store = JsonlStore(home=tmp_path)
    m, ids = _scripted_board(store)
    assert m.is_closed()
    # predicate views equal across a fresh fold over the journal
    r = store.load_state("b1")
    assert census(r, ids["q1"]) == census(m.state, ids["q1"])
    assert is_refuted(r, ids["n1"]) == is_refuted(m.state, ids["n1"])
    assert m.q_status(ids["q1"]) == (r.questions[ids["q1"]].status,
                                     r.questions[ids["q1"]].outcome)
    assert r.canvas == m.state.canvas
    assert r.carried_unresolved == m.state.carried_unresolved


def test_reload_after_every_mutation_loop(tmp_path):
    """The strict AC4 loop: after every single mutation call the store folds
    to an identical BoardState (includes all consequence events)."""
    store = JsonlStore(home=tmp_path)
    m = VerdictMachine(store, "b1")
    m.create_board("b1", "Justice (Republic Book I)", "participates", "async")
    h1 = m.enroll_handle("h1")
    h2 = m.enroll_handle("h2")
    h3 = m.enroll_handle("h3")
    f1 = m.enroll_handle("facilitator", is_facilitator=True)
    n1 = m.register_node("n1", "Justice is the advantage of the stronger.")
    ce1, q1 = m.open_refutation_q(n1, "3a", opened_by=h1)
    actions = [
        lambda: m.cast(q1, h1, "explicit", "stands"),
        lambda: m.cast(q1, h2, "explicit", "stands"),
        lambda: m.record_ambient(q1, f1, "stands"),
        lambda: m.record_ambient(q1, h3, "rebutted"),
        lambda: m.cast(q1, h1, "explicit", "rebutted"),   # re-vote
        lambda: m.toggle_medium("live"),
        lambda: m.set_socrates(h1),
        lambda: m.open_governance_q("mode_switch", subject="facilitates",
                                    opened_by=h1),
        lambda: m.cast(q1, h1, "explicit", "stands"),     # refused? no — open
    ]
    for act in actions:
        act()
        assert store.load_state("b1") == m.state
    # governance settlement fires consequence events — still identical fold
    q2 = m.open_governance_q("mode_switch", subject="facilitates",
                             opened_by=h1)
    for who in (h1, h2, h3):
        m.cast(q2, who, "explicit", "for")
    assert store.load_state("b1") == m.state


def test_fresh_machine_reopen_identical_and_seq_continues(tmp_path):
    store = JsonlStore(home=tmp_path)
    m, ids = _scripted_board(store)
    last_seq = m.state.seq
    m2 = VerdictMachine(store, "b1")
    assert m2.state == m.state
    assert m2.state.seq == last_seq

    store2 = JsonlStore(home=tmp_path / "other")
    a = VerdictMachine(store2, "b2")
    a.create_board("b2", "Justice (Republic Book I)")
    a.enroll_handle("h1")
    a.enroll_handle("h2")
    a.register_node("n1", "a claim")
    b = VerdictMachine(store2, "b2")
    assert b.state.seq == a.state.seq
    new_id = b.enroll_handle("h3")
    assert b.state.seq == a.state.seq + 1
    assert b.state.handles[new_id].display == "h3"


def test_one_line_per_mutation(tmp_path):
    store = JsonlStore(home=tmp_path)
    m = VerdictMachine(store, "b3")
    m.create_board("b3", "Justice (Republic Book I)")
    m.enroll_handle("h1")
    m.enroll_handle("h2")
    n1 = m.register_node("n1", "a claim")
    m.open_refutation_q(n1, "3a", opened_by="h1")
    m.set_socrates("h1")
    m.toggle_medium("live")
    events = store.read_all("b3")
    assert len(events) == 7                 # seven mutations → seven lines
    assert [e["type"] for e in events] == [
        "board_created", "handle_enrolled", "handle_enrolled",
        "node_registered", "q_opened", "socrates_set", "medium_toggled",
    ]
    # consequence events are journaled too: a settling cast adds q_settled
    q2 = m.open_governance_q("ingress_selection", subject="x", opened_by="h1")
    m.cast(q2, "h1", "explicit", "for")
    m.cast(q2, "h2", "explicit", "for")
    events = store.read_all("b3")
    types = [e["type"] for e in events]
    assert types.count("q_settled") == 1


def test_torn_line_survives(tmp_path):
    store = JsonlStore(home=tmp_path)
    m = VerdictMachine(store, "b4")
    m.create_board("b4", "Justice (Republic Book I)")
    m.enroll_handle("h1")
    good = m.state.seq
    path = store.path_for("b4")
    with open(path, "a") as fh:
        fh.write('{"seq": 99, "ty')            # torn final line
    events = store.read_all("b4")
    assert len(events) == 2                    # torn line skipped, not fatal
    loaded = store.load_state("b4")
    assert loaded.seq == good
    # the journal still accepts new appends after the torn tail
    m2 = VerdictMachine(store, "b4")
    h2 = m2.enroll_handle("h2")
    assert m2.state.seq == good + 1
    assert store.load_state("b4") == m2.state
    assert m2.state.handles[h2].display == "h2"