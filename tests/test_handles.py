"""Handle identities: duplicate-display suffixing, provisional binding,
facilitator eligibility guards."""

import pytest

from board.machine import (
    FacilitatorCannotVote,
    FacilitatorNeverProposes,
    UnknownHandle,
    UnknownQuestion,
)


def test_duplicate_display_auto_suffixed(make_env):
    env = make_env(humans=("a", "b"))
    m = env.machine
    id1 = m.enroll_handle("Glaucon")
    id2 = m.enroll_handle("Glaucon")
    id3 = m.enroll_handle("Glaucon")
    assert id1 != id2 != id3
    assert m.state.handles[id1].display == "Glaucon"
    assert m.state.handles[id2].display == "Glaucon#2"
    assert m.state.handles[id3].display == "Glaucon#3"


def test_bind_name_renames_provisional(make_env):
    env = make_env(humans=("a", "b"))
    m = env.machine
    pid = m.enroll_handle("SPEAKER-07", kind="provisional")
    assert m.state.handles[pid].kind == "provisional"
    rid = m.bind_name(pid, "Adeimantus")
    assert rid == pid
    assert m.state.handles[pid].kind == "bound"
    assert m.state.handles[pid].display == "Adeimantus"
    # duplicate binding is suffixed like any display
    pid2 = m.enroll_handle("SPEAKER-08", kind="provisional")
    m.bind_name(pid2, "Adeimantus")
    assert m.state.handles[pid2].display == "Adeimantus#2"


def test_facilitator_cannot_vote_in_facilitates(make_env):
    env = make_env(humans=("a", "b"), mode="facilitates", facilitator=True)
    m, q = env.machine, env.q
    with pytest.raises(FacilitatorCannotVote):
        m.cast(q, env.f, "explicit", "stands")
    with pytest.raises(FacilitatorCannotVote):
        m.record_ambient(q, env.f, "stands", receive_time=1.0)


def test_facilitator_can_vote_in_participates(make_env):
    env = make_env(humans=("a", "b"), mode="participates", facilitator=True)
    m, q = env.machine, env.q
    ballot = m.cast(q, env.f, "explicit", "stands")
    assert ballot is not None
    assert m.counted(q, env.f).side == "stands"


def test_facilitator_never_proposes_close(make_env):
    env = make_env(humans=("a", "b"), mode="participates", facilitator=True)
    m = env.machine
    with pytest.raises(FacilitatorNeverProposes):
        m.open_governance_q("close", opened_by=env.f)
    with pytest.raises(FacilitatorNeverProposes):
        m.propose_close(opened_by=env.f)
    qc = m.propose_close(opened_by=env.h["a"])
    assert m.state.questions[qc].kind == "close"


def test_unknown_handle_and_question(make_env):
    env = make_env(humans=("a", "b"))
    m = env.machine
    with pytest.raises(UnknownQuestion):
        m.cast("q-none", env.h["a"], "explicit", "stands")
    with pytest.raises(UnknownHandle):
        m.cast(env.q, "ghost", "explicit", "stands")
    with pytest.raises(UnknownHandle):
        m.set_socrates("ghost")
    with pytest.raises(UnknownHandle):
        m.bind_name("ghost", "Cephalus")