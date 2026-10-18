"""SDF-15 — facilitator voice modes (spec stories 23, 24, 25, 26).

Seam: ``voice.facilitator.FacilitatorVoice`` (pure, headless, stdlib only).
Every facilitator contribution is a labeled post quoting the target id it
responds to; over-quota META and stale-target posts drop as moot and never
land on the poll/WS feed; ballots carry visible reasons at equal weight.
"""

import pytest

from voice.facilitator import FacilitatorVoice


def test_live_meta_quota_one_per_defender_turn():
    v = FacilitatorVoice(mode="participates", medium="live")
    first = v.post("META", target_id="seg-1", text="lesson one",
                   node_id="n1", turn_id="t1")
    second = v.post("META", target_id="seg-2", text="lesson two",
                    node_id="n1", turn_id="t1")
    assert first.status == "posted"
    assert second.status == "moot"
    # a new defender turn re-arms the quota
    third = v.post("META", target_id="seg-3", text="lesson three",
                   node_id="n1", turn_id="t2")
    assert third.status == "posted"


def test_async_meta_quota_one_per_revision_node():
    v = FacilitatorVoice(mode="participates", medium="async")
    first = v.post("META", target_id="n1", text="lesson one", node_id="n1")
    second = v.post("META", target_id="n1", text="lesson two", node_id="n1")
    assert first.status == "posted"
    assert second.status == "moot"
    # a new revision node re-arms the quota
    third = v.post("META", target_id="n2", text="lesson three", node_id="n2")
    assert third.status == "posted"


def test_facilitates_rooms_have_zero_meta():
    v = FacilitatorVoice(mode="facilitates", medium="async")
    post = v.post("META", target_id="n1", text="a lesson", node_id="n1")
    assert post.status == "moot"
    assert post not in v.feed()


def test_every_post_carries_type_plus_quoted_target():
    v = FacilitatorVoice(mode="participates", medium="async")
    with pytest.raises(ValueError):
        v.post("", target_id="n1", text="no type")
    with pytest.raises(ValueError):
        v.post("META", target_id="", text="no target", node_id="n1")
    with pytest.raises(ValueError):
        v.post("ELENCHUS", target_id="  ", text="blank target")
    post = v.post("ELENCHUS", target_id="ce1", text="a strike")
    assert post.kind == "ELENCHUS"
    assert post.target_id == "ce1"


def test_elenchus_unlimited_and_distinct_from_meta():
    v = FacilitatorVoice(mode="participates", medium="live")
    first = v.post("ELENCHUS", target_id="ce1", text="strike one",
                   node_id="n1", turn_id="t1")
    second = v.post("ELENCHUS", target_id="ce1", text="strike two",
                    node_id="n1", turn_id="t1")
    assert first.status == "posted"
    assert second.status == "posted"
    assert first.kind == "ELENCHUS" != "META"


def test_stale_target_self_cut_never_lands():
    v = FacilitatorVoice(mode="participates", medium="async")
    v.mark_target_moot("ce1")
    post = v.post("ELENCHUS", target_id="ce1", text="late strike")
    assert post.status == "moot"
    assert post not in v.feed()
    assert all(p.target_id != "ce1" for p in v.feed())


def test_suggestions_participates_only():
    v = FacilitatorVoice(mode="participates", medium="async")
    post = v.post("SUGGESTION", target_id="n1", text="try this")
    assert post.status == "posted"
    f = FacilitatorVoice(mode="facilitates", medium="async")
    muted = f.post("SUGGESTION", target_id="n1", text="try this")
    assert muted.status == "moot"
    assert muted not in f.feed()


def test_ballots_post_visible_reasons_at_equal_weight():
    v = FacilitatorVoice(mode="participates", medium="async")
    with pytest.raises(ValueError):
        v.ballot(target_id="ce1", side="stands", reason="")
    with pytest.raises(ValueError):
        v.ballot(target_id="ce1", side="stands", reason="   ")
    ballot = v.ballot(target_id="ce1", side="stands",
                      reason="the example is Justice under the definition")
    assert ballot.status == "posted"
    assert ballot.reason == \
        "the example is Justice under the definition"
    assert ballot.weight == 1
    assert ballot in v.feed()
