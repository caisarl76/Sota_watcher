import pytest


@pytest.fixture(autouse=True)
def tmp_db(tmp_path, monkeypatch):
    path = tmp_path / "watcher.db"
    monkeypatch.setenv("WATCHER_DB", str(path))
    return path
