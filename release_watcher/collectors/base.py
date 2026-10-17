"""Collector 공통 인터페이스와 HTTP 헬퍼."""

from __future__ import annotations

import time
from typing import Protocol

import httpx

from .. import config
from ..models import ChangeEvent, Snapshot, Source


class CollectorError(Exception):
    """이번 주기 수집 실패. Source.error_count 를 올리고 다음 주기로 넘긴다."""


class RateLimited(CollectorError):
    pass


class Collector(Protocol):
    source_type: str
    snapshot_kind: str

    def fetch(self, source: Source, prev: Snapshot | None) -> Snapshot:
        """현재 상태를 관찰한다. ETag 등은 source.meta 에 갱신하며, 호출자가 저장한다."""
        ...

    def diff(self, prev: Snapshot | None, cur: Snapshot) -> list[ChangeEvent]:
        """prev 가 None 이면 기준선이므로 이벤트를 내지 않는다."""
        ...


def make_client(headers: dict[str, str] | None = None) -> httpx.Client:
    return httpx.Client(
        timeout=config.HTTP_TIMEOUT_S,
        headers={"User-Agent": config.USER_AGENT, **(headers or {})},
        follow_redirects=True,
    )


def request(client: httpx.Client, method: str, url: str, **kwargs) -> httpx.Response:
    """네트워크 오류와 5xx 는 지수 백오프로 config.HTTP_RETRIES 회 재시도한다."""
    last: Exception | None = None
    for attempt in range(config.HTTP_RETRIES + 1):
        if attempt:
            time.sleep(config.RETRY_BASE_S * 2 ** (attempt - 1))
        try:
            resp = client.request(method, url, **kwargs)
        except httpx.TransportError as e:
            last = e
            continue
        if resp.status_code < 500:
            return resp
        last = CollectorError(f"HTTP {resp.status_code}")
    raise CollectorError(f"{method} {url} 실패: {last}") from last


def clip(text: str, limit: int = config.MAX_EVENT_DETAIL) -> str:
    """UTF-8 바이트 기준으로 자른다."""
    raw = text.encode()
    if len(raw) <= limit:
        return text
    return raw[: limit - 3].decode(errors="ignore") + "..."
