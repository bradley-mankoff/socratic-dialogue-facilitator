"""SDF-18 — share URLs and sleep resume (spec stories 41, 42).

One-command Quick Tunnel share URL plus QR LAN fallback; board identity
stays local with per-mutation persistence; sleep and crash resume drops
live mics, keeps centroids, and rejoins guests on the current URL. No
stable public URL is promised without a named tunnel.
"""

from tests.sdf5_stubs import make_service


def _decided_board(tmp_path):
    """Board with decided state: claim + CE + settled majority votes."""
    svc = make_service(tmp_path / "store")
    opened = svc.open_board("Justice", "room-a")
    bid = opened.board_id
    machine = svc.machine(bid)
    h1 = machine.enroll_handle("Cephalus")
    h2 = machine.enroll_handle("Polemarchus")
    h3 = machine.enroll_handle("Thrasymachus")
    claim = svc.claim_original(bid, "Justice is the advantage of the stronger.",
                               claimant_display="Thrasymachus")
    alg = svc.allege(bid, "3a", by_display="Cephalus")
    svc.cast_vote(bid, alg.q_id, "stands", handle_id=h1)
    svc.cast_vote(bid, alg.q_id, "stands", handle_id=h2)
    svc.cast_vote(bid, alg.q_id, "rebutted", handle_id=h3)
    return svc, bid, {"node_id": claim.node_id, "q_id": alg.q_id}


def test_share_command_yields_joinable_quick_url():
    from server.share import classify_url, quick_tunnel_command, share_info

    assert quick_tunnel_command(8765) == \
        "cloudflared tunnel --url http://localhost:8765"
    url = "https://brave-words-1234.trycloudflare.com"
    assert classify_url(url) == "quick"
    info = share_info(url)
    assert info["url"] == url
    assert info["stable"] is False
    assert "rotat" in info["note"].lower()  # rotating per run
    assert "dev" in info["note"].lower() or "sla" in info["note"].lower()


def test_lan_fallback_needs_no_third_party():
    from server.share import classify_url, lan_url, qr_payload, share_info

    url = lan_url("192.168.1.20", 8765)
    assert url == "http://192.168.1.20:8765"
    assert classify_url(url) == "lan"
    assert qr_payload(url) == url  # the QR encodes the URL verbatim
    info = share_info(url)
    assert info["stable"] is False
    assert "third part" in info["note"].lower()


def test_no_stable_public_url_without_named_tunnel():
    from server.share import is_stable_public

    quick = "https://brave-words-1234.trycloudflare.com"
    assert is_stable_public(quick, named_tunnel=False) is False
    # A rotating Quick Tunnel host is never a stable promise — even when a
    # named tunnel exists elsewhere, this URL still rotates.
    assert is_stable_public(quick, named_tunnel=True) is False
    assert is_stable_public("http://192.168.1.20:8765",
                            named_tunnel=False) is False
    assert is_stable_public("https://board.example.com",
                            named_tunnel=False) is False
    assert is_stable_public("https://board.example.com",
                            named_tunnel=True) is True


def test_kill_restart_reconstructs_decided_state_exactly(tmp_path):
    svc, bid, _ = _decided_board(tmp_path)
    state_before = svc.state(bid).to_dict()
    score_before = svc.scoreboard(bid)
    log_before = svc.read_system_log(bid)
    record_before = svc.board(bid).to_dict()

    # Kill: drop every in-memory handle; restart: a fresh service over the
    # same data root replays the journal from disk.
    killed = make_service(tmp_path / "store")

    assert killed.state(bid).to_dict() == state_before
    assert killed.scoreboard(bid) == score_before
    assert killed.read_system_log(bid) == log_before
    assert killed.board(bid).to_dict() == record_before


def test_board_identity_stays_local_not_url(tmp_path):
    svc, bid, _ = _decided_board(tmp_path)
    record_before = svc.board(bid).to_dict()

    first = svc.share_quick_tunnel(bid, 8765)
    second = svc.share_lan(bid, "192.168.1.20", 8765)
    assert first["command"] == \
        "cloudflared tunnel --url http://localhost:8765"
    assert second["url"] == "http://192.168.1.20:8765"
    assert first["kind"] == "quick" and second["kind"] == "lan"
    assert first["stable"] is False and second["stable"] is False

    assert svc.board(bid).to_dict() == record_before
    assert svc.board(bid).board_id == bid
    # The registry row carries (X, label) identity — never a share URL.
    assert "url" not in record_before


def test_bad_centroid_input_raises_value_error(tmp_path):
    """Bad enroll input is a ValueError, never a bare TypeError."""
    import pytest

    from voice.session import EnrollmentStore

    store = EnrollmentStore(tmp_path / "store")
    with pytest.raises(ValueError):
        store.enroll("b1", "h1", None)
    with pytest.raises(ValueError):
        store.enroll("b1", "h1", [None])
    with pytest.raises(ValueError):
        store.enroll("b1", "h1", [0.1, float("nan")])
    with pytest.raises(ValueError):
        store.enroll("b1", "h1", [])
    assert store.centroids("b1") == {}  # nothing persisted the refusal


def test_corrupt_voice_file_degrades_gracefully(tmp_path):
    """A hand-edited voice.json with bad entries never tracebacks:
    good centroids survive, bad ones are skipped, and the store stays
    writable (repo convention: corrupt durable files degrade, not crash)."""
    import json

    from voice.session import EnrollmentStore

    board_dir = tmp_path / "store" / "b1"
    board_dir.mkdir(parents=True)
    (board_dir / "voice.json").write_text(json.dumps(
        {"centroids": {"h1": None, "h2": [0.1, 0.2],
                        "h3": [None], "h4": "nope"}}))
    store = EnrollmentStore(tmp_path / "store")
    assert store.centroids("b1") == {"h2": [0.1, 0.2]}
    assert store.handles("b1") == ["h2"]
    assert store.centroid("b1", "h1") is None
    # The read-then-write path survives the corrupt file too.
    store.enroll("b1", "h9", [0.5])
    assert store.centroid("b1", "h9") == [0.5]
    assert store.centroid("b1", "h2") == [0.1, 0.2]


def test_sleep_resume_drops_mics_keeps_centroids_rejoins_on_url(tmp_path):
    from voice.session import EnrollmentStore, LiveMics

    svc, bid, ids = _decided_board(tmp_path)
    state_before = svc.state(bid).to_dict()
    machine = svc.machine(bid)
    handles = {h.display: hid for hid, h in machine.state.handles.items()}

    enrollments = EnrollmentStore(tmp_path / "store")
    enrollments.enroll(bid, handles["Cephalus"], [0.1, 0.2, 0.3])
    enrollments.enroll(bid, handles["Polemarchus"], [0.4, 0.5, 0.6])

    mics = LiveMics()
    mics.attach(bid, handles["Cephalus"], "mic-cephalus")
    mics.attach(bid, handles["Polemarchus"], "mic-pole")
    assert len(mics.active(bid)) == 2

    current = "https://fresh-words-5678.trycloudflare.com"
    report = svc.resume_board(bid, current_url=current,
                              live_mics=mics,
                              enrollment_store=enrollments)

    assert report["dropped_live_mics"] == 2
    assert mics.active(bid) == {}
    # Centroids are keyed by handle_id (displays can suffix on collision).
    assert report["kept_centroids"] == [handles["Cephalus"],
                                          handles["Polemarchus"]]
    assert enrollments.centroid(bid, handles["Cephalus"]) == [0.1, 0.2, 0.3]
    assert report["rejoin_url"] == current  # guests rejoin on current URL
    assert report["board_id"] == bid  # identity is (X, label), not the URL
    assert svc.state(bid).to_dict() == state_before  # decided state intact
