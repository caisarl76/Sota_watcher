from datetime import datetime, timedelta, timezone

from release_watcher import db
from release_watcher.models import Snapshot


def test_retention_and_dedupe():
    conn = db.connect()
    tid = db.add_target(conn, "t", "https://x.org")
    sid = db.add_source(conn, tid, "project_page", "https://x.org")
    t0 = datetime(2026, 10, 1, tzinfo=timezone.utc)
    for i in range(7):
        assert db.save_snapshot(conn, Snapshot(sid, "repo", {"i": i}, t0 + timedelta(hours=i)))
    assert not db.save_snapshot(conn, Snapshot(sid, "repo", {"i": 6}, t0 + timedelta(hours=9)))
    assert db.count_snapshots(conn, sid) == 5
    assert db.latest_snapshot(conn, sid, "repo").data == {"i": 6}
    # 다른 kind 는 별도로 유지
    db.save_snapshot(conn, Snapshot(sid, "page_text", {"t": 1}, t0))
    assert db.count_snapshots(conn, sid) == 6
