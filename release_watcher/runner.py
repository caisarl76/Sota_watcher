"""한 주기의 오케스트레이션.

현재(2단계)는 수집까지만: Source 별 스냅샷 수집 → diff → 스냅샷 저장.
룰 필터·LLM 분류·알림은 3·4단계에서 이어 붙인다.
"""

from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass, field

from . import db, state
from .collectors import CollectorError, get_collector
from .models import ChangeEvent, Source, Target

log = logging.getLogger(__name__)


@dataclass
class CollectResult:
    events: list[ChangeEvent] = field(default_factory=list)
    collected: int = 0  # 수집에 성공한 소스 수
    failed: list[tuple[Source, str]] = field(default_factory=list)
    skipped: int = 0  # 아직 Collector 가 없는 소스 타입
    transition: state.Transition | None = None


def collect_source(conn: sqlite3.Connection, source: Source, collector=None) -> list[ChangeEvent]:
    """CollectorError 는 error_count 를 올린 뒤 다시 던진다."""
    collector = collector or get_collector(source.type)
    prev = db.latest_snapshot(conn, source.id, collector.snapshot_kind)
    try:
        cur = collector.fetch(source, prev)
    except CollectorError:
        with conn:
            db.bump_source_error(conn, source.id)
        raise
    events = collector.diff(prev, cur)
    with conn:
        db.save_snapshot(conn, cur)
        db.update_source(conn, source.id, source.meta, 0)
    return events


def collect_target(conn: sqlite3.Connection, target: Target) -> CollectResult:
    res = CollectResult()
    for src in db.list_sources(conn, target.id):
        collector = get_collector(src.type)
        if collector is None:
            res.skipped += 1
            continue
        try:
            res.events += collect_source(conn, src, collector)
            res.collected += 1
        except CollectorError as e:
            log.info("source %s 수집 실패: %s", src.url, e)
            res.failed.append((src, str(e)))

    with conn:
        db.touch_target(conn, target.id, changed=bool(res.events))
        # 모든 소스가 첫 스냅샷을 가지면 new → watching
        if target.state == "new" and res.collected and not res.failed:
            tr = state.on_first_snapshot(target.state)
            db.set_state(conn, target.id, tr.next)
            res.transition = tr
    return res
