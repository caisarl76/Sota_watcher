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
python -m pytest   # 테스트는 네트워크 차단 상태(respx)로 돈다. GitHub 는 tests/fake_github.py 사용
watch --help
```

## 진행 상황

- [x] 1단계: 패키지 뼈대, DB/마이그레이션, `watch add/list/show/remove/pause/resume`, `watch add --from`, 상태 머신
- [x] 2단계: GitHub Collector (`collectors/github.py`), 스냅샷 저장/보존, `runner.collect_target`, `watch collect`(개발용)
- [ ] 3단계: 룰 필터 + `rules.yaml`
- [ ] 4단계: LLM 분류, Slack, `watch run`
- [ ] 5단계 이후: docs/DESIGN.md 로드맵 참고

## 구현 메모 (설계 문서와 다른 점)

- `Collector.fetch(source, prev)` 는 이전 스냅샷을 받는다 (304 응답 시 이전 값을 재사용하기 위해). ETag 는 `source.meta["etags"]` 에 저장.
- GitHub 스냅샷은 kind `repo` 하나에 트리·HEAD·릴리스·태그·README·새 커밋을 JSON 으로 담는다. 내용이 같으면 저장하지 않는다.
- GitHub 404 는 오류가 아니라 `exists: false` 로 기록하고, 이후 생기면 `repo_created` 이벤트를 낸다.
- 첫 스냅샷(기준선)에서는 이벤트를 내지 않는다. `watch add` 가 첫 수집을 수행하고 성공하면 `new → watching`.
- `watch collect` 는 이벤트를 출력만 하고 `events` 테이블에 기록하지 않는다 (룰 라벨이 생기는 3단계 이후 `watch run` 이 기록).
