"""GitHub REST API 의 필요한 부분만 흉내 내는 가짜 서버 (respx side_effect 용).

owner/repo 는 구분하지 않는다. ETag/304, commits?since, 빈 저장소 409 를 재현한다.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone

import httpx


class FakeGitHub:
    def __init__(self):
        self.exists = True
        self.default_branch = "main"
        self.commits: list[dict] = []  # 최신순
        self.tree: set[str] = set()
        self.readme: str | None = None
        self.releases: list[dict] = []
        self.tags: list[str] = []
        self.log: list[tuple[str, int]] = []  # (path, status)
        self.fail: dict[str, list[httpx.Response]] = {}  # path suffix → 먼저 돌려줄 응답들
        self._clock = datetime(2026, 10, 1, tzinfo=timezone.utc)

    # --- 시나리오 조작 ---

    def commit(self, message: str, files: dict[str, str]) -> str:
        """files: path → added|modified|removed"""
        self._clock += timedelta(hours=1)
        sha = hashlib.sha1(f"{message}{self._clock}".encode()).hexdigest()
        for path, status in files.items():
            (self.tree.discard if status == "removed" else self.tree.add)(path)
        self.commits.insert(0, {"sha": sha, "message": message, "files": files,
                                "date": self._clock.strftime("%Y-%m-%dT%H:%M:%SZ")})
        return sha

    def requests_since(self, n: int) -> list[tuple[str, int]]:
        return self.log[n:]

    # --- respx side_effect ---

    def handle(self, request: httpx.Request) -> httpx.Response:
        resp = self._route(request)
        self.log.append((request.url.path, resp.status_code))
        return resp

    def _route(self, request):
        parts = request.url.path.strip("/").split("/")[3:]  # repos/o/r 이후
        sub = "/".join(parts)
        for suffix, queue in self.fail.items():
            if sub == suffix and queue:
                return queue.pop(0)
        q = dict(request.url.params)

        if not self.exists:
            return httpx.Response(404, json={"message": "Not Found"})
        if sub == "":
            return self._cond(request, {"default_branch": self.default_branch, "private": False})
        if sub == "commits":
            if not self.commits:
                return httpx.Response(409, json={"message": "Git Repository is empty."})
            items = [c for c in self.commits if not q.get("since") or c["date"] >= q["since"]]
            return self._cond(request, [self._commit_json(c) for c in items[: int(q.get("per_page", 30))]])
        if parts[:1] == ["commits"] and len(parts) == 2:
            c = next(c for c in self.commits if c["sha"] == parts[1])
            return httpx.Response(200, json={
                **self._commit_json(c),
                "files": [{"filename": p, "status": s} for p, s in c["files"].items()],
            })
        if parts[:2] == ["git", "trees"]:
            if not self.commits:
                return httpx.Response(409, json={"message": "Git Repository is empty."})
            return httpx.Response(200, json={"truncated": False,
                                             "tree": [{"path": p, "type": "blob"} for p in sorted(self.tree)]})
        if sub == "readme":
            if self.readme is None:
                return httpx.Response(404, json={"message": "Not Found"})
            return httpx.Response(200, text=self.readme)
        if sub == "releases":
            return self._cond(request, [
                {"tag_name": t, "name": t, "draft": False, "published_at": "2026-10-02T00:00:00Z",
                 "html_url": f"https://github.com/o/r/releases/tag/{t}"} for t in self.releases])
        if sub == "tags":
            if not self.commits:
                return httpx.Response(409, json={"message": "Git Repository is empty."})
            return self._cond(request, [{"name": t} for t in self.tags])
        return httpx.Response(404, json={"message": f"unhandled {sub}"})

    @staticmethod
    def _commit_json(c):
        return {"sha": c["sha"], "html_url": f"https://github.com/o/r/commit/{c['sha']}",
                "commit": {"message": c["message"], "committer": {"date": c["date"]}}}

    @staticmethod
    def _cond(request, body):
        raw = json.dumps(body).encode()
        etag = '"' + hashlib.md5(raw + str(request.url.query).encode()).hexdigest() + '"'
        if request.headers.get("if-none-match") == etag:
            return httpx.Response(304, headers={"etag": etag})
        return httpx.Response(200, content=raw, headers={"etag": etag, "content-type": "application/json"})
