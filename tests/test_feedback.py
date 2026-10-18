"""Feedback capture wired into the hash-chained audit log. Stdlib only."""

import pytest

from retail.audit import AuditLog
from retail.feedback import (
    ACTION,
    ACTOR,
    FeedbackError,
    capture_feedback,
    list_feedback,
)


def make_log():
    log = AuditLog()
    log.record("planner", "ask", {"q": "which SKUs are at stockout risk?"})
    return log


def test_thumbs_up_without_correction_appends():
    log = make_log()
    event = capture_feedback(
        log, session_id="s1", turn_id="t1", rating="up")
    assert event["actor"] == ACTOR
    assert event["action"] == ACTION
    assert event["details"]["session_id"] == "s1"
    assert event["details"]["turn_id"] == "t1"
    assert event["details"]["rating"] == "up"
    assert log.verify_chain()


def test_thumbs_down_with_correction_appends():
    log = make_log()
    event = capture_feedback(
        log, session_id="s2", turn_id="t7", rating="down",
        correction="  overstated on-hand for SKU-BEANS-001  ")
    assert event["details"]["rating"] == "down"
    assert event["details"]["correction"] == "overstated on-hand for SKU-BEANS-001"
    assert log.verify_chain()


def test_thumbs_down_without_correction_rejected():
    log = make_log()
    with pytest.raises(FeedbackError):
        capture_feedback(log, session_id="s1", turn_id="t1", rating="down")


def test_whitespace_correction_rejected():
    log = make_log()
    with pytest.raises(FeedbackError):
        capture_feedback(
            log, session_id="s1", turn_id="t1", rating="down",
            correction="   ")


def test_out_of_range_rating_rejected():
    log = make_log()
    with pytest.raises(FeedbackError):
        capture_feedback(
            log, session_id="s1", turn_id="t1", rating="maybe",
            correction="x")


def test_blank_session_or_turn_rejected():
    log = make_log()
    with pytest.raises(FeedbackError):
        capture_feedback(log, session_id="  ", turn_id="t1", rating="up")
    with pytest.raises(FeedbackError):
        capture_feedback(log, session_id="s1", turn_id="", rating="up")
    assert log.verify_chain()


def test_interleaved_feedback_chain_verifies_and_lists_only_feedback():
    log = make_log()
    capture_feedback(log, session_id="s1", turn_id="t1", rating="up")
    log.record("planner", "gate_approve", {"gate": "GATE-0001"})
    capture_feedback(log, session_id="s1", turn_id="t2", rating="down",
                     correction="wrong supplier lead time")
    assert log.verify_chain()
    fb = list_feedback(log)
    assert len(fb) == 2
    assert [e["details"]["turn_id"] for e in fb] == ["t1", "t2"]


def test_tampered_feedback_breaks_chain():
    log = make_log()
    capture_feedback(log, session_id="s1", turn_id="t1", rating="up")
    assert log.verify_chain()
    log._events[-1]["details"]["rating"] = "down"
    assert not log.verify_chain()
