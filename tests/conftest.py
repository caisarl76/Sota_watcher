import pytest
import respx

from release_watcher import config

from .fake_github import FakeGitHub


@pytest.fixture(autouse=True)
def tmp_db(tmp_path, monkeypatch):
    path = tmp_path / "watcher.db"
    monkeypatch.setenv("WATCHER_DB", str(path))
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    return path


@pytest.fixture(autouse=True)
def http(monkeypatch):
    """네트워크 차단: 모킹되지 않은 요청은 respx 가 실패시킨다."""
    monkeypatch.setattr(config, "RETRY_BASE_S", 0)
    with respx.mock(assert_all_called=False) as router:
        yield router


@pytest.fixture
def gh(http):
    fake = FakeGitHub()
    http.route(host="api.github.com").mock(side_effect=fake.handle)
    return fake
