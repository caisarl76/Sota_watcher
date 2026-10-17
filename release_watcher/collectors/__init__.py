from .base import Collector, CollectorError, RateLimited
from .github import GitHubCollector

# 소스 타입 → Collector 팩토리. 나머지 타입은 7·8단계에서 추가한다.
COLLECTORS = {
    "github": GitHubCollector,
}


def get_collector(source_type: str) -> Collector | None:
    factory = COLLECTORS.get(source_type)
    return factory() if factory else None


__all__ = ["Collector", "CollectorError", "RateLimited", "GitHubCollector", "COLLECTORS", "get_collector"]
