"""typer 앱: add / list / show / pause / resume / remove."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import typer

from . import db, state
from .models import RELEASE_CATEGORIES
from .resolver import InvalidURL, normalize_url, resolve

app = typer.Typer(help="논문/프로젝트의 코드·모델 공개를 추적한다.", no_args_is_help=True)


def _parse_wants(raw: str | None) -> list[str] | None:
    if not raw:
        return None
    wants = [w.strip() for w in raw.split(",") if w.strip()]
    bad = [w for w in wants if w not in RELEASE_CATEGORIES]
    if bad or not wants:
        raise typer.BadParameter(
            f"알 수 없는 카테고리 {bad}. 허용: {', '.join(RELEASE_CATEGORIES)}", param_hint="--wants"
        )
    return wants


@dataclass
class AddResult:
    status: str  # added|duplicate|invalid
    url: str
    target_id: int | None = None
    message: str = ""


def register(conn: sqlite3.Connection, raw_url: str, title: str | None = None,
             wants: list[str] | None = None) -> AddResult:
    try:
        src = resolve(raw_url)
        origin = normalize_url(raw_url)
    except InvalidURL as e:
        return AddResult("invalid", raw_url.strip(), message=str(e))

    existing = db.find_target_by_url(conn, origin) or db.find_target_by_url(conn, src.url)
    if existing:
        return AddResult("duplicate", origin, existing.id)

    with conn:
        tid = db.add_target(conn, title or src.title_hint, origin, wants)
        db.add_source(conn, tid, src.type, src.url, src.meta)
    # TODO(7단계): 프로젝트 페이지에서 GitHub/HF/arXiv 링크를 추출해 소스 추가
    # TODO(4단계): 등록 직후 1회 분류 → 이미 공개된 대상은 released 로 두고 알리지 않음
    return AddResult("added", origin, tid, src.type)


def _read_url_file(path: Path) -> list[str]:
    urls = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            urls.append(line)
    return urls


@app.command()
def add(
    url: Optional[str] = typer.Argument(None, help="프로젝트 페이지, arXiv, GitHub, HF URL"),
    from_file: Optional[Path] = typer.Option(
        None, "--from", exists=True, dir_okay=False, help="한 줄에 URL 하나인 파일로 일괄 등록"
    ),
    title: Optional[str] = typer.Option(None, "--title", help="대상 제목"),
    wants: Optional[str] = typer.Option(None, "--wants", help="관심 카테고리 (쉼표 구분)"),
) -> None:
    """추적 대상을 등록한다."""
    if bool(url) == bool(from_file):
        raise typer.BadParameter("URL 또는 --from 중 하나만 지정하세요.")
    wants_list = _parse_wants(wants)
    conn = db.connect()

    if url:
        r = register(conn, url, title, wants_list)
        if r.status == "added":
            typer.echo(f"등록됨 #{r.target_id} [{r.message}] {r.url}")
        elif r.status == "duplicate":
            typer.echo(f"이미 등록됨 #{r.target_id} {r.url}")
        else:
            typer.echo(f"실패: {r.message}", err=True)
            raise typer.Exit(1)
        return

    if title:
        raise typer.BadParameter("--title 은 --from 과 함께 쓸 수 없습니다.")
    counts = {"added": 0, "duplicate": 0, "invalid": 0}
    for line in _read_url_file(from_file):
        r = register(conn, line, None, wants_list)
        counts[r.status] += 1
        if r.status == "invalid":
            typer.echo(f"  건너뜀(잘못된 URL): {r.url} — {r.message}", err=True)
    typer.echo(f"등록 {counts['added']}건, 중복 {counts['duplicate']}건, 실패 {counts['invalid']}건")


@app.command("list")
def list_(state_: Optional[str] = typer.Option(None, "--state", help="상태로 필터")) -> None:
    """대상 목록."""
    rows = db.list_targets(db.connect(), state_)
    if not rows:
        typer.echo("등록된 대상이 없습니다.")
        return
    typer.echo(f"{'ID':>4}  {'STATE':<9} {'SRC':>3}  {'LAST CHECKED':<20} TITLE")
    for t, n in rows:
        typer.echo(f"{t.id:>4}  {t.state:<9} {n:>3}  {(t.last_checked or '-'):<20} {t.title}")


def _get_or_exit(conn: sqlite3.Connection, target_id: int):
    t = db.get_target(conn, target_id)
    if not t:
        typer.echo(f"대상 #{target_id} 없음", err=True)
        raise typer.Exit(1)
    return t


@app.command()
def show(target_id: int) -> None:
    """소스 목록, 최근 이벤트 20건, 분류 이력."""
    conn = db.connect()
    t = _get_or_exit(conn, target_id)
    typer.echo(f"#{t.id} {t.title}")
    typer.echo(f"  URL     {t.origin_url}")
    typer.echo(f"  상태    {t.state}")
    typer.echo(f"  관심    {', '.join(t.wants)}")
    typer.echo(f"  등록    {t.created_at}   마지막 확인 {t.last_checked or '-'}   마지막 변경 {t.last_change or '-'}")
    if t.summary:
        typer.echo(f"  요약    {t.summary}")

    typer.echo("\n소스")
    for s in db.list_sources(conn, t.id):
        err = f"  (오류 {s.error_count}회)" if s.error_count else ""
        typer.echo(f"  [{s.id}] {s.type:<12} {s.url}{err}")

    events = db.recent_events(conn, t.id)
    typer.echo(f"\n최근 이벤트 ({len(events)})")
    for e in events:
        typer.echo(f"  {e['observed_at']}  {e['rule_label']:<9} {e['kind']:<13} {e['summary']}")

    cls = db.classifications(conn, t.id)
    typer.echo(f"\n분류 이력 ({len(cls)})")
    for c in cls:
        typer.echo(f"  {c['created_at']}  {c['model']}  → {c['decided_state']}")


def _transition(target_id: int, fn) -> None:
    conn = db.connect()
    t = _get_or_exit(conn, target_id)
    try:
        tr = fn(t.state)
    except state.InvalidTransition as e:
        typer.echo(str(e), err=True)
        raise typer.Exit(1)
    with conn:
        db.set_state(conn, t.id, tr.next)
    typer.echo(f"#{t.id} {tr.prev} → {tr.next}")


@app.command("pause")
def pause_(target_id: int) -> None:
    """추적을 멈춘다."""
    _transition(target_id, state.pause)


@app.command("resume")
def resume_(target_id: int) -> None:
    """멈춘 추적을 재개한다."""
    _transition(target_id, state.resume)


@app.command()
def remove(target_id: int, yes: bool = typer.Option(False, "--yes", "-y", help="확인 생략")) -> None:
    """대상과 하위 데이터를 삭제한다."""
    conn = db.connect()
    t = _get_or_exit(conn, target_id)
    if not yes:
        typer.confirm(f"#{t.id} {t.title} 을(를) 삭제할까요?", abort=True)
    with conn:
        db.remove_target(conn, t.id)
    typer.echo(f"삭제됨 #{t.id}")


if __name__ == "__main__":
    app()
