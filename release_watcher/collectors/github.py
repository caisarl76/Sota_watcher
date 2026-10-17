"""GitHub 저장소 Collector: 커밋, 파일 트리, 릴리스/태그, README.

변경 없는 저장소는 조건부 요청 4건(repo, commits, releases, tags)이 모두 304 로 끝나
rate limit 을 소모하지 않는다. 트리와 README 는 HEAD 가 바뀐 경우에만 다시 받는다.

스냅샷 data:
    exists, url, default_branch,
    head: {sha, date} | None        (빈 저장소면 None)
    tree: [path...], tree_truncated
    releases: [{tag, name, url, published_at}], tags: [name...]
    readme: str | None
    new_commits: [{sha, message, date, url, files: [{path, status}] | None}]
        이전 스냅샷 이후 새 커밋 (기준선이면 빈 목록)
"""

from __future__ import annotations

import difflib
import os
import re
from datetime import datetime, timezone
from urllib.parse import urlencode

import httpx

from .. import config
from ..models import ChangeEvent, Snapshot, Source
from .base import CollectorError, RateLimited, clip, make_client, request

API = "https://api.github.com"
RAW = "application/vnd.github.raw+json"

# README 에서 "아직 미공개" 를 뜻하는 문구. _PHRASE 는 알림 요약에 인용할 짧은 표현.
_PHRASE = re.compile(
    r"coming\s+soon|\bTBD\b|\bTODO\b|\bto\s+be\s+released\b|\bwill\s+be\s+(?:released|available|open[- ]sourced)\b"
    r"|stay\s+tuned",
    re.IGNORECASE,
)
COMING_SOON = re.compile(
    _PHRASE.pattern
    + r"|\bsoon\b.*\b(?:code|weights?|checkpoints?|models?)\b|\b(?:code|weights?|checkpoints?)\b.*\bsoon\b",
    re.IGNORECASE,
)

_EMPTY = {"exists": True, "head": None, "tree": [], "releases": [], "tags": [], "readme": None}


class GitHubCollector:
    source_type = "github"
    snapshot_kind = "repo"

    def __init__(self, client: httpx.Client | None = None, token: str | None = None):
        token = token if token is not None else os.environ.get("GITHUB_TOKEN", "")
        headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        self.client = client or make_client(headers)

    # --- fetch -------------------------------------------------------------

    def fetch(self, source: Source, prev: Snapshot | None) -> Snapshot:
        owner, repo = source.meta["owner"], source.meta["repo"]
        base = f"{API}/repos/{owner}/{repo}"
        p = prev.data if prev else None
        conditional = bool(p and p.get("exists"))
        old_etags = source.meta.get("etags", {}) if conditional else {}
        etags: dict[str, str] = {}

        def get(url: str, params: dict | None = None, accept: str | None = None,
                cond: bool = False) -> httpx.Response:
            key = url + ("?" + urlencode(params) if params else "")
            headers = {"Accept": accept} if accept else {}
            if cond and key in old_etags:
                headers["If-None-Match"] = old_etags[key]
            resp = request(self.client, "GET", url, params=params, headers=headers)
            if resp.status_code in (403, 429) and resp.headers.get("x-ratelimit-remaining") == "0":
                raise RateLimited(f"GitHub rate limit 초과 (reset={resp.headers.get('x-ratelimit-reset')})")
            if cond:
                if resp.status_code == 200 and "etag" in resp.headers:
                    etags[key] = resp.headers["etag"]
                elif resp.status_code == 304:
                    etags[key] = old_etags[key]
            return resp

        def fail(resp: httpx.Response) -> CollectorError:
            return CollectorError(f"GET {resp.request.url} → HTTP {resp.status_code}")

        data: dict = {"url": f"https://github.com/{owner}/{repo}"}

        # 저장소 메타. 404 는 오류가 아니라 "아직 없음(또는 비공개)".
        r = get(base, cond=True)
        if r.status_code == 404:
            source.meta.pop("etags", None)
            return self._snap(source, {**data, "exists": False})
        if r.status_code == 304:
            data["default_branch"] = p["default_branch"]
        elif r.status_code == 200:
            data["default_branch"] = r.json().get("default_branch") or "main"
        else:
            raise fail(r)
        data["exists"] = True

        # 커밋 목록 (최신순). 이전 HEAD 날짜 이후만 받고, 이전 HEAD sha 에서 끊는다.
        prev_head = p.get("head") if conditional else None
        params = {"sha": data["default_branch"], "per_page": 100}
        if prev_head:
            params["since"] = prev_head["date"]
        r = get(f"{base}/commits", params, cond=True)
        listing: list[dict] = []
        if r.status_code == 304:
            head = prev_head
        elif r.status_code == 409:  # 빈 저장소
            head = None
        elif r.status_code == 200:
            listing = r.json()
            head = ({"sha": listing[0]["sha"], "date": listing[0]["commit"]["committer"]["date"]}
                    if listing else prev_head)
        else:
            raise fail(r)
        data["head"] = head

        new_commits: list[dict] = []
        if p is not None:  # 기준선에서는 과거 커밋을 이벤트로 만들지 않는다
            stop = prev_head["sha"] if prev_head else None
            for i, c in enumerate(listing):
                if c["sha"] == stop:
                    break
                files = None
                if i < config.MAX_COMMIT_DETAIL:
                    d = get(f"{base}/commits/{c['sha']}")
                    if d.status_code == 200:
                        files = [{"path": f["filename"], "status": f["status"]}
                                 for f in d.json().get("files", [])]
                new_commits.append({
                    "sha": c["sha"],
                    "message": c["commit"]["message"],
                    "date": c["commit"]["committer"]["date"],
                    "url": c.get("html_url") or f"{data['url']}/commit/{c['sha']}",
                    "files": files,
                })
        data["new_commits"] = new_commits

        # 파일 트리 + README: HEAD 가 같으면 이전 값을 재사용
        if head is None:
            data.update(tree=[], tree_truncated=False, readme=None)
        elif conditional and prev_head and prev_head["sha"] == head["sha"]:
            data.update(tree=p["tree"], tree_truncated=p.get("tree_truncated", False), readme=p["readme"])
        else:
            r = get(f"{base}/git/trees/{head['sha']}", {"recursive": 1})
            if r.status_code == 200:
                body = r.json()
                data["tree"] = sorted(t["path"] for t in body.get("tree", []) if t.get("type") == "blob")
                data["tree_truncated"] = bool(body.get("truncated"))
            elif r.status_code in (404, 409):
                data.update(tree=[], tree_truncated=False)
            else:
                raise fail(r)
            r = get(f"{base}/readme", accept=RAW)
            if r.status_code == 200:
                data["readme"] = r.text
            elif r.status_code == 404:
                data["readme"] = None
            else:
                raise fail(r)

        # 릴리스 / 태그
        r = get(f"{base}/releases", {"per_page": 20}, cond=True)
        if r.status_code == 304:
            data["releases"] = p["releases"]
        elif r.status_code == 200:
            data["releases"] = [
                {"tag": x["tag_name"], "name": x.get("name") or x["tag_name"],
                 "url": x.get("html_url", ""), "published_at": x.get("published_at")}
                for x in r.json() if not x.get("draft")
            ]
        else:
            raise fail(r)

        r = get(f"{base}/tags", {"per_page": 50}, cond=True)
        if r.status_code == 304:
            data["tags"] = p["tags"]
        elif r.status_code == 200:
            data["tags"] = [t["name"] for t in r.json()]
        elif r.status_code == 409:
            data["tags"] = []
        else:
            raise fail(r)

        source.meta["etags"] = etags  # 이번에 쓴 URL 의 ETag 만 남긴다
        source.meta["default_branch"] = data["default_branch"]
        return self._snap(source, data)

    def _snap(self, source: Source, data: dict) -> Snapshot:
        return Snapshot(source.id, self.snapshot_kind, data, datetime.now(timezone.utc))

    # --- diff --------------------------------------------------------------

    def diff(self, prev: Snapshot | None, cur: Snapshot) -> list[ChangeEvent]:
        c = cur.data
        if prev is None or not c.get("exists"):
            return []
        p = prev.data
        url = c["url"]
        events: list[ChangeEvent] = []

        def ev(kind, summary, detail="", link=url):
            events.append(ChangeEvent(cur.source_id, kind, summary, clip(detail), link, cur.taken_at))

        if not p.get("exists"):
            ev("repo_created", f"저장소 공개됨: {url.removeprefix('https://github.com/')}")
            p = _EMPTY

        # 커밋
        for cm in reversed(c.get("new_commits", [])):
            title, _, body = cm["message"].partition("\n")
            lines = [body.strip()] if body.strip() else []
            if cm["files"] is not None:
                lines += [f"{f['status']}: {f['path']}" for f in cm["files"]]
            ev("commit", f"commit {cm['sha'][:7]}: {title.strip()}", "\n".join(lines), cm["url"])

        # 파일 트리
        branch = c.get("default_branch", "main")
        before, after = set(p.get("tree", [])), set(c.get("tree", []))
        self._file_events(ev, "file_added", "파일 추가", sorted(after - before), url, branch)
        if not c.get("tree_truncated") and not p.get("tree_truncated"):  # 잘린 트리는 삭제 판단 불가
            self._file_events(ev, "file_removed", "파일 삭제", sorted(before - after), url, branch)

        # 릴리스 / 태그
        old_rel = {x["tag"] for x in p.get("releases", [])}
        for x in c.get("releases", []):
            if x["tag"] not in old_rel:
                ev("release", f"릴리스 {x['tag']}: {x['name']}", f"published_at: {x['published_at']}",
                   x["url"] or f"{url}/releases/tag/{x['tag']}")
        rel_tags = {x["tag"] for x in c.get("releases", [])}
        old_tags = set(p.get("tags", []))
        for t in c.get("tags", []):
            if t not in old_tags and t not in rel_tags:
                ev("release", f"태그 생성: {t}", "", f"{url}/tree/{t}")

        # README 의 coming soon 류 문구 소실
        readme_ev = readme_marker_change(p.get("readme"), c.get("readme"))
        if readme_ev:
            ev("page_text", *readme_ev, f"{url}#readme")
        return events

    @staticmethod
    def _file_events(ev, kind, label, paths, url, branch):
        head, rest = paths[: config.MAX_FILE_EVENTS], paths[config.MAX_FILE_EVENTS:]
        for path in head:
            ev(kind, f"{label}: {path}", path, f"{url}/blob/{branch}/{path}")
        if rest:
            ev(kind, f"{label}: 외 {len(rest)}개", "\n".join(rest), url)


def readme_marker_change(old: str | None, new: str | None) -> tuple[str, str] | None:
    """README 에서 coming soon 류 문구가 줄었으면 (summary, detail) 를 돌려준다."""
    if not old:
        return None
    old_lines, new_lines = old.splitlines(), (new or "").splitlines()
    old_marked = [ln for ln in old_lines if COMING_SOON.search(ln)]
    new_marked = [ln for ln in new_lines if COMING_SOON.search(ln)]
    gone = [ln for ln in old_marked if ln not in new_lines]
    if not gone or len(new_marked) >= len(old_marked):
        return None
    m = _PHRASE.search(gone[0])
    phrase = m.group(0) if m else "soon"
    added = [ln[1:] for ln in difflib.unified_diff(old_lines, new_lines, lineterm="", n=0)
             if ln.startswith("+") and not ln.startswith("+++") and ln[1:].strip()]
    detail = "\n".join([f"- {ln.strip()}" for ln in gone] + [f"+ {ln.strip()}" for ln in added[:30]])
    return f"README: '{phrase.strip()}' 문구 사라짐", detail
