"""URL → 소스 타입 판별과 정규화.

프로젝트 페이지에서 GitHub/HF/arXiv 링크를 추출하는 기능은 로드맵 7단계에서 추가한다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from urllib.parse import urlsplit, urlunsplit

from .models import SourceType

_GITHUB_RESERVED = {
    "orgs", "users", "settings", "marketplace", "topics", "collections",
    "explore", "features", "sponsors", "login", "join", "about", "pricing",
}
_HF_RESERVED = {"docs", "blog", "papers", "settings", "login", "join", "pricing", "learn", "tasks"}
_ARXIV_ID = re.compile(r"^/(?:abs|pdf|html)/([a-z\-]+(?:\.[A-Z]{2})?/\d{7}|\d{4}\.\d{4,5})(?:v\d+)?(?:\.pdf)?/?$")


class InvalidURL(ValueError):
    pass


@dataclass
class ResolvedSource:
    type: SourceType
    url: str  # 정규화된 감시 URL
    meta: dict = field(default_factory=dict)
    title_hint: str = ""


def normalize_url(raw: str) -> str:
    raw = raw.strip()
    if not raw:
        raise InvalidURL("빈 URL")
    if "://" not in raw:
        raw = "https://" + raw
    parts = urlsplit(raw)
    if parts.scheme not in ("http", "https") or not parts.netloc or "." not in parts.netloc:
        raise InvalidURL(f"지원하지 않는 URL: {raw}")
    host = parts.netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    path = parts.path.rstrip("/")
    # fragment 는 버리고, query 는 일반 페이지에서만 의미가 있을 수 있어 유지한다.
    return urlunsplit((parts.scheme.lower(), host, path, parts.query, ""))


def resolve(raw: str) -> ResolvedSource:
    url = normalize_url(raw)
    parts = urlsplit(url)
    host, segs = parts.netloc, [s for s in parts.path.split("/") if s]

    if host == "github.com":
        if len(segs) >= 2 and segs[0] not in _GITHUB_RESERVED:
            owner, repo = segs[0], segs[1].removesuffix(".git")
            return ResolvedSource(
                "github", f"https://github.com/{owner}/{repo}",
                {"owner": owner, "repo": repo}, f"{owner}/{repo}",
            )
        raise InvalidURL(f"GitHub 저장소 URL이 아님: {url}")

    if host == "huggingface.co":
        repo_type = "model"
        if segs and segs[0] in ("datasets", "spaces"):
            repo_type = segs[0].removesuffix("s")
            segs = segs[1:]
        if len(segs) >= 2 and segs[0] not in _HF_RESERVED:
            repo_id = f"{segs[0]}/{segs[1]}"
            prefix = {"model": "", "dataset": "datasets/", "space": "spaces/"}[repo_type]
            return ResolvedSource(
                "huggingface", f"https://huggingface.co/{prefix}{repo_id}",
                {"repo_id": repo_id, "hf_repo_type": repo_type}, repo_id,
            )
        raise InvalidURL(f"Hugging Face 저장소 URL이 아님: {url}")

    if host in ("arxiv.org", "export.arxiv.org"):
        m = _ARXIV_ID.match(parts.path)
        if not m:
            raise InvalidURL(f"arXiv 논문 URL이 아님: {url}")
        arxiv_id = m.group(1)
        return ResolvedSource(
            "arxiv", f"https://arxiv.org/abs/{arxiv_id}", {"arxiv_id": arxiv_id}, f"arXiv:{arxiv_id}",
        )

    return ResolvedSource("project_page", url, {}, host + (parts.path or ""))
