from datetime import datetime, timedelta

import pytest

from release_watcher import state
from release_watcher.models import DEFAULT_WANTS


def test_first_snapshot_moves_new_to_watching():
    assert state.on_first_snapshot("new").next == "watching"
    assert not state.on_first_snapshot("watching").changed


def test_partial_when_some_wants_pass():
    tr = state.apply_classification("watching", DEFAULT_WANTS, {"inference_code"})
    assert (tr.next, tr.notify) == ("partial", ["inference_code"])


def test_released_when_all_wants_pass_in_one_cycle():
    tr = state.apply_classification("watching", ["model_release", "inference_code"],
                                    {"model_release", "inference_code"})
    assert tr.next == "released"
    assert tr.notify == ["inference_code", "model_release"]  # 1건으로 묶어 보냄


def test_partial_to_released_notifies_only_remaining():
    tr = state.apply_classification("partial", ["model_release", "inference_code"],
                                    {"model_release", "inference_code"},
                                    already_notified={"inference_code"})
    assert (tr.next, tr.notify) == ("released", ["model_release"])


def test_already_notified_category_is_suppressed():
    tr = state.apply_classification("partial", DEFAULT_WANTS, {"inference_code"},
                                    already_notified={"inference_code"})
    assert not tr.changed and tr.notify == []


def test_unwanted_and_docs_only_are_ignored():
    tr = state.apply_classification("watching", ["model_release"], {"inference_code", "docs_only"})
    assert not tr.changed and tr.notify == []


def test_narrow_wants_releases_on_single_category():
    tr = state.apply_classification("watching", ["model_release"], {"model_release"})
    assert (tr.next, tr.notify) == ("released", ["model_release"])


@pytest.mark.parametrize("s", ["new", "released", "paused"])
def test_inactive_states_ignore_classification(s):
    tr = state.apply_classification(s, DEFAULT_WANTS, set(DEFAULT_WANTS))
    assert not tr.changed and tr.notify == []


def test_pause_resume():
    assert state.pause("partial").next == "paused"
    assert state.resume("paused").next == "watching"
    with pytest.raises(state.InvalidTransition):
        state.pause("released")
    with pytest.raises(state.InvalidTransition):
        state.resume("watching")


def test_auto_pause_after_180_days():
    now = datetime(2026, 10, 16)
    created = now - timedelta(days=365)
    assert state.should_auto_pause("watching", None, created, now, 180)
    assert not state.should_auto_pause("watching", now - timedelta(days=10), created, now, 180)
    assert not state.should_auto_pause("released", None, created, now, 180)
