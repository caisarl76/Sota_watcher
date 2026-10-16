"""Target 상태 머신. DB와 무관한 순수 함수로 둔다.

    new ──첫 스냅샷──▶ watching ──일부 wants──▶ partial ──남은 wants──▶ released
                         │  └────────── wants 전부 ──────────────────▶ released
                         └─ pause / 180일 무변경 ─▶ paused ──resume──▶ watching
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta

ACTIVE_STATES = ("watching", "partial")


class InvalidTransition(ValueError):
    pass


@dataclass(frozen=True)
class Transition:
    prev: str
    next: str
    notify: list[str] = field(default_factory=list)  # 이번에 처음 알릴 카테고리

    @property
    def changed(self) -> bool:
        return self.prev != self.next


def on_first_snapshot(state: str) -> Transition:
    if state == "new":
        return Transition(state, "watching")
    return Transition(state, state)


def apply_classification(
    state: str,
    wants: list[str],
    passed: set[str] | list[str],
    already_notified: set[str] | list[str] = (),
) -> Transition:
    """임계값을 통과한 카테고리(passed)를 상태에 반영한다.

    - wants 밖의 카테고리와 이미 알린 카테고리는 알리지 않는다.
    - 알린 카테고리 누적이 wants 전부를 덮으면 released, 아니면 partial.
    """
    if state not in ACTIVE_STATES:
        return Transition(state, state)
    wanted = set(wants)
    notified = set(already_notified) & wanted
    fresh = (set(passed) & wanted) - notified
    if not fresh:
        return Transition(state, state)
    covered = notified | fresh
    nxt = "released" if covered >= wanted else "partial"
    return Transition(state, nxt, sorted(fresh))


def pause(state: str) -> Transition:
    if state in ("new", *ACTIVE_STATES):
        return Transition(state, "paused")
    raise InvalidTransition(f"{state} 상태에서는 pause 할 수 없음")


def resume(state: str) -> Transition:
    if state == "paused":
        return Transition(state, "watching")
    raise InvalidTransition(f"{state} 상태에서는 resume 할 수 없음")


def should_auto_pause(state: str, last_change: datetime | None, created_at: datetime,
                      now: datetime, days: int) -> bool:
    if state not in ACTIVE_STATES:
        return False
    ref = last_change or created_at
    return now - ref >= timedelta(days=days)
