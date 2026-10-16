"""SQLite 연결, 마이그레이션, 리포지토리 함수."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from . import config
from .models import DEFAULT_WANTS, Source, Target


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def connect(path: Path | None = None) -> sqlite3.Connection:
    path = Path(path or config.db_path())
    if str(path) != ":memory:":
        path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    migrate(conn)
    return conn


def migrate(conn: sqlite3.Connection) -> None:
    """migrations/NNN_*.sql 을 PRAGMA user_version 기준으로 순서대로 적용한다."""
    current = conn.execute("PRAGMA user_version").fetchone()[0]
    for f in sorted(config.MIGRATIONS_DIR.glob("[0-9][0-9][0-9]_*.sql")):
        version = int(f.name[:3])
        if version <= current:
            continue
        with conn:
            conn.executescript(f.read_text(encoding="utf-8"))
            conn.execute(f"PRAGMA user_version = {version}")


# --- targets ---------------------------------------------------------------

def _row_to_target(row: sqlite3.Row) -> Target:
    return Target(
        id=row["id"], title=row["title"], origin_url=row["origin_url"],
        wants=json.loads(row["wants"]), state=row["state"], created_at=row["created_at"],
        summary=row["summary"], last_checked=row["last_checked"], last_change=row["last_change"],
    )


def add_target(conn: sqlite3.Connection, title: str, origin_url: str,
               wants: list[str] | None = None, summary: str | None = None) -> int:
    cur = conn.execute(
        "INSERT INTO targets (title, origin_url, summary, wants, created_at) VALUES (?, ?, ?, ?, ?)",
        (title, origin_url, summary, json.dumps(wants or DEFAULT_WANTS), utcnow()),
    )
    return cur.lastrowid


def find_target_by_url(conn: sqlite3.Connection, url: str) -> Target | None:
    row = conn.execute("SELECT * FROM targets WHERE origin_url = ?", (url,)).fetchone()
    return _row_to_target(row) if row else None


def get_target(conn: sqlite3.Connection, target_id: int) -> Target | None:
    row = conn.execute("SELECT * FROM targets WHERE id = ?", (target_id,)).fetchone()
    return _row_to_target(row) if row else None


def list_targets(conn: sqlite3.Connection, state: str | None = None) -> list[tuple[Target, int]]:
    """(Target, 소스 수) 목록."""
    sql = """SELECT t.*, COUNT(s.id) AS n_sources FROM targets t
             LEFT JOIN sources s ON s.target_id = t.id"""
    args: tuple = ()
    if state:
        sql += " WHERE t.state = ?"
        args = (state,)
    sql += " GROUP BY t.id ORDER BY t.id"
    return [(_row_to_target(r), r["n_sources"]) for r in conn.execute(sql, args)]


def set_state(conn: sqlite3.Connection, target_id: int, state: str) -> None:
    conn.execute("UPDATE targets SET state = ? WHERE id = ?", (state, target_id))


def remove_target(conn: sqlite3.Connection, target_id: int) -> bool:
    return conn.execute("DELETE FROM targets WHERE id = ?", (target_id,)).rowcount > 0


# --- sources ---------------------------------------------------------------

def add_source(conn: sqlite3.Connection, target_id: int, type_: str, url: str,
               meta: dict | None = None) -> int | None:
    """이미 있는 (target, url) 이면 None."""
    cur = conn.execute(
        "INSERT OR IGNORE INTO sources (target_id, type, url, meta) VALUES (?, ?, ?, ?)",
        (target_id, type_, url, json.dumps(meta or {})),
    )
    return cur.lastrowid if cur.rowcount else None


def list_sources(conn: sqlite3.Connection, target_id: int) -> list[Source]:
    rows = conn.execute("SELECT * FROM sources WHERE target_id = ? ORDER BY id", (target_id,))
    return [
        Source(id=r["id"], target_id=r["target_id"], type=r["type"], url=r["url"],
               meta=json.loads(r["meta"] or "{}"), error_count=r["error_count"])
        for r in rows
    ]


# --- history (show) --------------------------------------------------------

def recent_events(conn: sqlite3.Connection, target_id: int, limit: int = 20) -> list[sqlite3.Row]:
    return conn.execute(
        """SELECT e.* FROM events e JOIN sources s ON s.id = e.source_id
           WHERE s.target_id = ? ORDER BY e.observed_at DESC, e.id DESC LIMIT ?""",
        (target_id, limit),
    ).fetchall()


def classifications(conn: sqlite3.Connection, target_id: int, limit: int = 20) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM classifications WHERE target_id = ? ORDER BY created_at DESC, id DESC LIMIT ?",
        (target_id, limit),
    ).fetchall()


def notified_categories(conn: sqlite3.Connection, target_id: int) -> set[str]:
    rows = conn.execute(
        "SELECT DISTINCT category FROM notifications WHERE target_id = ? AND status IN ('queued', 'sent')",
        (target_id,),
    )
    return {r["category"] for r in rows}
