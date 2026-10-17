import httpx
from typer.testing import CliRunner

from release_watcher import db
from release_watcher.cli import app

runner = CliRunner()


def invoke(*args):
    return runner.invoke(app, list(args))


def test_add_and_list(gh):
    r = invoke("add", "https://github.com/x/y")
    assert r.exit_code == 0, r.output
    assert "등록됨 #1 [github, 첫 스냅샷 저장]" in r.output

    r = invoke("list")
    assert "x/y" in r.output and "watching" in r.output

    r = invoke("add", "https://github.com/x/y/")
    assert "이미 등록됨 #1" in r.output


def test_add_with_wants_and_title():
    r = invoke("add", "https://huggingface.co/org/m", "--title", "My Model", "--wants", "model_release")
    assert r.exit_code == 0, r.output
    t = db.get_target(db.connect(), 1)
    assert t.title == "My Model" and t.wants == ["model_release"]


def test_add_rejects_bad_wants():
    r = invoke("add", "https://github.com/x/y", "--wants", "docs_only")
    assert r.exit_code != 0


def test_add_from_tabs_file(tmp_path, gh):
    lines = [f"https://github.com/owner{i}/repo{i}" for i in range(18)]
    lines += ["https://github.com/owner0/repo0", "", "# comment", "not a url", "https://arxiv.org/abs/2410.00001"]
    f = tmp_path / "tabs.txt"
    f.write_text("\n".join(lines))

    r = invoke("add", "--from", str(f))
    assert r.exit_code == 0, r.output
    assert "등록 19건, 중복 1건, 실패 1건" in r.output
    rows = db.list_targets(db.connect())
    assert len(rows) == 19 and all(n == 1 for _, n in rows)


def test_add_from_20_lines(tmp_path):
    f = tmp_path / "tabs.txt"
    f.write_text("\n".join(f"https://lab{i}.github.io/proj" for i in range(20)))
    r = invoke("add", "--from", str(f))
    assert "등록 20건" in r.output


def test_show_pause_resume_remove():
    invoke("add", "https://arxiv.org/abs/2410.12345")
    r = invoke("show", "1")
    assert r.exit_code == 0 and "arxiv" in r.output and "https://arxiv.org/abs/2410.12345" in r.output

    assert "new → paused" in invoke("pause", "1").output
    assert "paused → watching" in invoke("resume", "1").output
    assert invoke("resume", "1").exit_code == 1

    r = invoke("remove", "1", "--yes")
    assert "삭제됨 #1" in r.output
    conn = db.connect()
    assert db.get_target(conn, 1) is None
    assert conn.execute("SELECT COUNT(*) FROM sources").fetchone()[0] == 0  # cascade


def test_show_missing():
    assert invoke("show", "99").exit_code == 1


def test_add_requires_exactly_one_input(tmp_path):
    assert invoke("add").exit_code != 0


def test_add_keeps_new_state_when_first_fetch_fails(http):
    http.route(host="api.github.com").mock(return_value=httpx.Response(502))
    r = invoke("add", "https://github.com/x/y")
    assert r.exit_code == 0 and "첫 수집 실패" in r.output
    conn = db.connect()
    assert db.get_target(conn, 1).state == "new"
    assert db.list_sources(conn, 1)[0].error_count == 1


def test_collect_command_prints_events(gh):
    invoke("add", "https://github.com/x/y")
    gh.commit("Release inference code", {"inference.py": "added"})
    r = invoke("collect", "--target", "1")
    assert r.exit_code == 0, r.output
    assert "이벤트 2건" in r.output and "file_added    파일 추가: inference.py" in r.output
