import httpx
import pytest

from release_watcher import config, db
from release_watcher.collectors import CollectorError, GitHubCollector, RateLimited
from release_watcher.collectors.github import readme_marker_change
from release_watcher.runner import collect_source


@pytest.fixture
def conn():
    return db.connect()


@pytest.fixture
def source(conn):
    tid = db.add_target(conn, "o/r", "https://github.com/o/r")
    db.add_source(conn, tid, "github", "https://github.com/o/r", {"owner": "o", "repo": "r"})
    return db.list_sources(conn, tid)[0]


def collect(conn, source):
    src = db.list_sources(conn, source.target_id)[0]  # DB 에 저장된 meta(ETag) 사용
    return collect_source(conn, src, GitHubCollector())


def kinds(events):
    return [(e.kind, e.summary) for e in events]


def test_baseline_emits_no_events(conn, source, gh):
    gh.commit("init", {"README.md": "added"})
    assert collect(conn, source) == []
    snap = db.latest_snapshot(conn, source.id, "repo")
    assert snap.data["tree"] == ["README.md"] and snap.data["head"]["sha"] == gh.commits[0]["sha"]


def test_empty_repo_then_code_added(conn, source, gh):
    """완료 조건: 빈 레포 → 코드 추가 시 file_added 이벤트."""
    assert collect(conn, source) == []  # 빈 저장소 (commits 409)
    assert db.latest_snapshot(conn, source.id, "repo").data["head"] is None

    gh.commit("Initial code release\n\nInference + weights", {
        "README.md": "added", "inference.py": "added", "requirements.txt": "added",
        "ckpt/model.safetensors": "added",
    })
    events = collect(conn, source)
    assert kinds(events) == [
        ("commit", "commit " + gh.commits[0]["sha"][:7] + ": Initial code release"),
        ("file_added", "파일 추가: README.md"),
        ("file_added", "파일 추가: ckpt/model.safetensors"),
        ("file_added", "파일 추가: inference.py"),
        ("file_added", "파일 추가: requirements.txt"),
    ]
    commit = events[0]
    assert "Inference + weights" in commit.detail and "added: inference.py" in commit.detail
    assert events[3].url == "https://github.com/o/r/blob/main/inference.py"
    assert all(e.source_id == source.id for e in events)


def test_unchanged_repo_is_four_conditional_requests(conn, source, gh):
    gh.commit("init", {"README.md": "added"})
    gh.readme = "# Project\nCode coming soon"
    collect(conn, source)
    collect(conn, source)  # 기준선 다음 1회는 commits?since= 로 URL 이 바뀌어 200
    n = len(gh.log)

    assert collect(conn, source) == []
    calls = gh.requests_since(n)
    assert [s for _, s in calls] == [304, 304, 304, 304]  # repo, commits, releases, tags
    assert not any("/git/trees/" in p or p.endswith("/readme") for p, _ in calls)
    assert db.count_snapshots(conn, source.id) == 1  # 내용이 같으면 저장 안 함


def test_new_commit_only_reports_commits_after_prev_head(conn, source, gh):
    gh.commit("init", {"README.md": "added"})
    collect(conn, source)
    gh.commit("add train script", {"train.py": "added"})
    gh.commit("fix typo", {"README.md": "modified"})
    events = collect(conn, source)
    assert [e.summary.split(": ", 1)[1] for e in events if e.kind == "commit"] == ["add train script", "fix typo"]
    assert ("file_added", "파일 추가: train.py") in kinds(events)


def test_file_removed(conn, source, gh):
    gh.commit("init", {"README.md": "added", "old.py": "added"})
    collect(conn, source)
    gh.commit("cleanup", {"old.py": "removed"})
    assert ("file_removed", "파일 삭제: old.py") in kinds(collect(conn, source))


def test_readme_coming_soon_disappears(conn, source, gh):
    gh.commit("init", {"README.md": "added"})
    gh.readme = "# HumanoidPolicy-X\n\n## Code\nCode and weights coming soon!\n"
    collect(conn, source)

    gh.commit("update readme", {"README.md": "modified"})
    gh.readme = "# HumanoidPolicy-X\n\n## Code\nDownload weights from https://huggingface.co/o/m\n"
    page = [e for e in collect(conn, source) if e.kind == "page_text"]
    assert len(page) == 1
    assert page[0].summary == "README: 'coming soon' 문구 사라짐"
    assert "- Code and weights coming soon!" in page[0].detail
    assert "+ Download weights from https://huggingface.co/o/m" in page[0].detail


def test_release_and_tag(conn, source, gh):
    gh.commit("init", {"README.md": "added"})
    collect(conn, source)
    gh.releases = ["v1.0"]
    gh.tags = ["v1.0", "weights-v1"]
    assert kinds(collect(conn, source)) == [
        ("release", "릴리스 v1.0: v1.0"),
        ("release", "태그 생성: weights-v1"),
    ]


def test_repo_404_then_created(conn, source, gh):
    gh.exists = False
    assert collect(conn, source) == []
    assert db.latest_snapshot(conn, source.id, "repo").data == {"url": "https://github.com/o/r", "exists": False}

    gh.exists = True
    gh.commit("Initial commit", {"README.md": "added", "demo.py": "added"})
    k = kinds(collect(conn, source))
    assert k[0] == ("repo_created", "저장소 공개됨: o/r")
    assert ("commit", "commit " + gh.commits[0]["sha"][:7] + ": Initial commit") in k
    assert ("file_added", "파일 추가: demo.py") in k


def test_many_files_are_grouped(conn, source, gh, monkeypatch):
    monkeypatch.setattr(config, "MAX_FILE_EVENTS", 3)
    collect(conn, source)
    gh.commit("dump", {f"src/f{i}.py": "added" for i in range(5)})
    added = [e for e in collect(conn, source) if e.kind == "file_added"]
    assert len(added) == 4 and added[-1].summary == "파일 추가: 외 2개"
    assert added[-1].detail == "src/f3.py\nsrc/f4.py"


def test_commit_detail_limit(conn, source, gh, monkeypatch):
    monkeypatch.setattr(config, "MAX_COMMIT_DETAIL", 1)
    gh.commit("init", {"README.md": "added"})
    collect(conn, source)
    gh.commit("older", {"a.py": "added"})
    gh.commit("newer", {"b.py": "added"})
    n = len(gh.log)
    commits = [e for e in collect(conn, source) if e.kind == "commit"]
    assert sum("/commits/" in p for p, _ in gh.requests_since(n)) == 1  # 최신 1개만 상세 조회
    assert commits[0].detail == "" and commits[1].detail == "added: b.py"


def test_rate_limit_raises_and_counts_error(conn, source, gh):
    gh.fail[""] = [httpx.Response(403, headers={"x-ratelimit-remaining": "0", "x-ratelimit-reset": "1"})]
    with pytest.raises(RateLimited):
        collect(conn, source)
    assert db.list_sources(conn, source.target_id)[0].error_count == 1
    assert db.latest_snapshot(conn, source.id, "repo") is None


def test_server_errors_are_retried(conn, source, gh):
    gh.fail[""] = [httpx.Response(502), httpx.Response(503)]
    collect(conn, source)  # 2회 재시도 후 성공
    assert db.latest_snapshot(conn, source.id, "repo") is not None

    gh.fail[""] = [httpx.Response(502)] * 3
    with pytest.raises(CollectorError):
        collect(conn, source)


def test_success_resets_error_count(conn, source, gh):
    gh.fail[""] = [httpx.Response(500)] * 3
    with pytest.raises(CollectorError):
        collect(conn, source)
    collect(conn, source)
    assert db.list_sources(conn, source.target_id)[0].error_count == 0


def test_authorization_header(conn, source, gh, monkeypatch, http):
    monkeypatch.setenv("GITHUB_TOKEN", "tok")
    collect(conn, source)
    req = http.calls.last.request
    assert req.headers["authorization"] == "Bearer tok"
    assert req.headers["user-agent"].startswith("release-watcher/")


@pytest.mark.parametrize("old,new,hit", [
    ("Code coming soon", "Code: see inference.py", True),
    ("Weights: TBD\nCode: TBD", "Weights: hf.co/x\nCode: TBD", True),
    ("Code coming soon", "Code coming soon\nNews: accepted!", False),
    ("Code coming soon", "Code: Coming Soon!", False),  # 문구만 바뀜
    (None, "anything", False),
    ("We will release the weights soon.", "", True),
])
def test_readme_marker_change(old, new, hit):
    assert (readme_marker_change(old, new) is not None) is hit
