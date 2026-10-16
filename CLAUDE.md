# Release Watcher

설계 문서: [docs/DESIGN.md](docs/DESIGN.md). 구현은 문서의 "구현 로드맵" 단계 순서를 따른다.

## 규칙

- 의존성은 `httpx`, `trafilatura`, `huggingface_hub`, `anthropic`, `typer`, `pyyaml` 6개 외에 추가하지 않는다 (테스트용 `pytest`, `respx` 제외).
- 모든 HTTP 요청은 `httpx` 로 하고 타임아웃을 반드시 지정한다 (`config.HTTP_TIMEOUT_S`).
- LLM 호출은 `release_watcher/classify/llm.py` 에서만 한다.
- 테스트는 네트워크 없이 통과해야 한다 (HTTP는 `respx` 로 모킹).
- 상태는 SQLite 하나(`data/watcher.db`, `WATCHER_DB` 로 변경 가능). ORM 없이 `sqlite3` + `migrations/*.sql`.
- 상태 전이 로직은 `state.py` 의 순수 함수로 두고 DB 접근과 분리한다.

## 개발

```bash
pip install -e '.[dev]'
pytest
watch --help
```

## 진행 상황

- [x] 1단계: 패키지 뼈대, DB/마이그레이션, `watch add/list/show/remove/pause/resume`, `watch add --from`, 상태 머신
- [ ] 2단계: GitHub Collector
- [ ] 3단계: 룰 필터 + `rules.yaml`
- [ ] 4단계: LLM 분류, Slack, `watch run`
- [ ] 5단계 이후: docs/DESIGN.md 로드맵 참고
