from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

SourceType = Literal["github", "project_page", "arxiv", "huggingface"]
TargetState = Literal["new", "watching", "partial", "released", "paused"]
RuleLabel = Literal["skip", "candidate", "strong"]
EventKind = Literal[
    "commit", "release", "file_added", "file_removed",
    "page_text", "link_added", "hf_file_added", "repo_created",
]

# 공개 카테고리 (wants 로 고를 수 있는 것)
RELEASE_CATEGORIES: tuple[str, ...] = (
    "model_release", "inference_code", "training_code", "dataset", "demo_space",
)
# LLM 이 낼 수 있는 전체 카테고리
CATEGORIES: tuple[str, ...] = RELEASE_CATEGORIES + ("docs_only", "unrelated")
DEFAULT_WANTS: list[str] = list(RELEASE_CATEGORIES)


@dataclass
class Target:
    id: int
    title: str
    origin_url: str
    wants: list[str]
    state: TargetState
    created_at: str
    summary: str | None = None
    last_checked: str | None = None
    last_change: str | None = None


@dataclass
class Source:
    id: int
    target_id: int
    type: SourceType
    url: str
    meta: dict = field(default_factory=dict)
    error_count: int = 0


@dataclass
class Snapshot:
    """Collector 가 한 번 관찰한 Source 상태. data 는 JSON 직렬화 가능해야 한다."""
    source_id: int
    kind: str  # repo|page_text|hf_files|...
    data: dict
    taken_at: datetime

    def canonical(self) -> bytes:
        return json.dumps(self.data, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()

    @property
    def content_hash(self) -> str:
        return hashlib.sha256(self.canonical()).hexdigest()


@dataclass
class ChangeEvent:
    source_id: int
    kind: EventKind
    summary: str  # 룰 필터와 LLM이 읽는 한 줄
    detail: str  # 커밋 메시지 본문, diff 발췌, 추가된 경로 등 (최대 2KB)
    url: str
    observed_at: datetime
