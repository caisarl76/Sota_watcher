"""환경변수, 임계값, 경로. 환경변수가 기본값보다 우선한다."""

from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MIGRATIONS_DIR = ROOT / "migrations"
RULES_PATH = ROOT / "rules.yaml"


def db_path() -> Path:
    # 테스트에서 monkeypatch 로 바꿀 수 있도록 호출 시점에 읽는다.
    return Path(os.environ.get("WATCHER_DB", ROOT / "data" / "watcher.db"))


def _float(name: str, default: float) -> float:
    return float(os.environ.get(name, default))


def _int(name: str, default: int) -> int:
    return int(os.environ.get(name, default))


# [thresholds]
NOTIFY_CONFIDENCE = _float("WATCH_NOTIFY_CONFIDENCE", 0.75)
REVIEW_CONFIDENCE = _float("WATCH_REVIEW_CONFIDENCE", 0.50)
AUTO_PAUSE_DAYS = _int("WATCH_AUTO_PAUSE_DAYS", 180)

# [llm]
LLM_MODEL = os.environ.get("WATCH_LLM_MODEL", "claude-haiku-4-5")
ESCALATE_MODEL = os.environ.get("WATCH_ESCALATE_MODEL", "")  # 비우면 재질의 안 함
MAX_INPUT_KB = _int("WATCH_MAX_INPUT_KB", 4)

# [collect]
MAX_COMMIT_DETAIL = _int("WATCH_MAX_COMMIT_DETAIL", 50)
HTTP_TIMEOUT_S = _float("WATCH_HTTP_TIMEOUT_S", 10)
USER_AGENT = "release-watcher/0.1 (+https://github.com/caisarl76/Sota_watcher)"
HTTP_RETRIES = 2  # 실패 시 지수 백오프 재시도 횟수
RETRY_BASE_S = _float("WATCH_RETRY_BASE_S", 1.0)
SNAPSHOT_KEEP = 5
MAX_EVENT_DETAIL = 2048  # ChangeEvent.detail 최대 바이트
MAX_FILE_EVENTS = 100  # 주기당 파일 단위 이벤트 상한 (초과분은 1건으로 묶음)
