# Release Watcher — 논문/프로젝트 코드·모델 공개 추적 기술 구현 문서

Oct 16, 2026 · @Jihun

## 개요

Release Watcher는 LinkedIn 등에서 발견한 "코드/모델 미공개" 논문·프로젝트 페이지를 등록해 두면, 주기적으로 공개 여부를 확인하고 실제 릴리스가 감지됐을 때만 Slack으로 알려주는 도구다. 크롬 탭에 쌓아두던 "나중에 다시 볼 것" 목록을 자동 감시 큐로 바꾸는 것이 목적이다.

**문제**

- 프로젝트 페이지에 "Code (coming soon)"만 있고 GitHub 저장소는 비어 있거나 README만 존재하는 경우가 많다.
- 탭으로 보관하면 재방문 시점을 놓치고, 재방문해도 변화 유무를 눈으로 비교해야 한다.
- 저장소에 커밋이 생겨도 README 오타 수정인지, 가중치·추론 코드 공개인지 구분하려면 직접 읽어야 한다.

**목표**

1. URL 하나(프로젝트 페이지, arXiv, GitHub, Hugging Face)로 추적 대상을 등록할 수 있다.
2. 하루 1\~2회 자동 점검하고, 변경 내용을 `model_release`, `inference_code`, `training_code`, `dataset`, `docs_only` 등으로 분류한다.
3. 모델·추론 코드·학습 코드·데이터셋·데모 중 어떤 카테고리든 처음 공개가 감지되면 알림을 보내고, 문서만 바뀐 경우는 조용히 기록한다.
4. 대상당 추가 비용이 거의 0에 가깝도록 LLM 호출은 룰 기반 필터를 통과한 변경에만 사용한다.

**비목표**

- LinkedIn 피드 자체를 크롤링해서 자동으로 대상을 발견하는 기능(1차 범위 밖, 수동 등록으로 시작).
- 공개된 코드를 실제로 실행·검증하는 기능.
- 웹 UI. 1차는 CLI + Slack 알림으로 충분하다.

**가정**

- 사용자 요청의 "jev같은 모델"은 저비용 LLM으로 커밋·diff를 분류한다는 의미로 해석했다. 분류 모델은 Claude Haiku로 고정하고, 상위 모델 재질의는 두지 않는다 (10/17 결정).
- 알림은 Slack DM으로 먼저 개발·검증한 뒤, 안정되면 팀 채널 공유로 확장한다 (10/17 결정). 이메일은 선택 사항.
- 등록 수단은 북마클릿을 1차 범위에 포함하고, 기존에 열어둔 크롬 탭을 일괄 등록하는 기능도 1차에 넣는다 (10/17 결정).

## 요구사항

**기능 요구사항**

| ID | 요구사항 | 우선순위 |
| --- | --- | --- |
| F1 | `watch add <url>` 로 대상을 등록하면 URL 종류를 자동 판별하고, 프로젝트 페이지에서 GitHub / arXiv / HF 링크를 추출해 함께 등록한다 | P0 |
| F2 | 등록된 GitHub 저장소의 신규 커밋, 릴리스, 태그, 파일 트리 변화를 수집한다 | P0 |
| F3 | 프로젝트 페이지의 본문 텍스트 스냅샷을 저장하고 이전 스냅샷과 diff 한다 ("coming soon" → 링크 등장 감지) | P0 |
| F4 | Hugging Face 저장소(모델/데이터셋) 생성 또는 가중치 파일 업로드를 감지한다 | P1 |
| F5 | 변경 묶음을 룰 기반 1차 필터 후 LLM(Haiku)으로 카테고리·신뢰도 분류한다 | P0 |
| F6 | 어떤 공개 카테고리든 신뢰도 임계값 이상으로 처음 감지되면 Slack DM으로 알린다 | P0 |
| F7 | 동일 대상·동일 카테고리 알림은 재발송하지 않는다 (상태 머신으로 억제) | P0 |
| F8 | `watch list / show / pause / remove` 로 대상과 이력을 조회·관리한다 | P1 |
| F9 | 주간 다이제스트: 아직 미공개인 대상 수, 지난 주 분류 결과 요약 | P2 |
| F10 | 북마클릿으로 현재 크롬 탭을 바로 등록한다 (`workflow_dispatch` 호출) | P0 |
| F11 | 기존에 열어둔 크롬 탭 URL 목록을 파일로 받아 일괄 등록한다 (`watch add --from tabs.txt`) | P0 |
| F12 | 검증 후 알림 대상을 팀 Slack 채널로 확장한다 | P1 |

**비기능 요구사항**

- 무료 티어 안에서 동작: GitHub API 인증 토큰 기준 5,000 req/h, GitHub Actions 2,000분/월 중 하루 2회 × 5분 이내 사용.
- 대상 100개까지 하루 LLM 비용 1달러 미만. 룰 필터가 변경 없는 대상(대부분)을 LLM 호출 전에 걸러낸다.
- 모든 상태는 저장소 안의 SQLite 파일 하나에 담겨 `git`으로 버전 관리되며, 로컬 cron으로 옮겨도 그대로 동작한다.
- 외부 사이트에 대한 요청은 대상당 하루 2회를 넘지 않고 User-Agent를 명시한다.
- 분류 실패(LLM 오류, 파싱 실패)는 알림 없이 `needs_review` 로 기록하고 다음 주기에 재시도한다.

## 시스템 아키텍처

단일 Python 패키지 안에서 Collector → 룰 필터 → LLM 분류기 → Notifier 가 순서대로 실행되는 배치 파이프라인이다. 서버나 큐 없이 cron 한 번에 끝나고, 모든 상태는 SQLite 파일 하나에 남는다.

&#91;embedded content: Release Watcher 아키텍처 · 3개 소스, 4단계 파이프라인, 저장소 1개\]

Collector가 소스별로 변경 이벤트를 만들고, 룰 필터가 "변경 없음"과 "명백한 문서 수정"을 걸러낸 뒤 남은 후보만 LLM에 보낸다. 분류 결과가 알림 기준을 넘고 상태 머신이 "첫 감지"로 판정할 때만 Slack으로 나간다.

**한 번의 실행 흐름 (`watch run`)**

1. `targets` 에서 `active` 상태인 대상을 읽는다.
2. 소스 타입별 Collector가 이전 스냅샷과 비교해 `ChangeEvent` 목록을 만든다 (커밋 N개, 파일 트리 diff, 페이지 텍스트 diff, HF 파일 목록 diff).
3. 룰 필터가 각 이벤트에 `skip | candidate | strong` 라벨을 붙인다. `skip` 은 기록만 한다.
4. `candidate`/`strong` 이벤트는 대상 단위로 묶어 LLM에 한 번 질의하고 JSON 분류 결과를 받는다.
5. 분류 결과를 대상 상태 머신에 적용하고, 전이가 발생하면 `notifications` 에 큐잉한다.
6. Notifier가 큐를 Slack으로 보내고 전송 결과를 기록한다.
7. `watcher.db` 변경 사항을 git commit & push 한다 (GitHub Actions 환경).

## 추적 대상 모델링

하나의 논문/프로젝트가 **Target** 이고, Target은 여러 **Source** 를 가진다. 사용자는 URL 하나만 넣고, 시스템이 페이지에서 나머지 소스를 찾아 붙인다.

| 소스 타입 | 식별 규칙 | 감시 대상 | 감지 신호 |
| --- | --- | --- | --- |
| `github` | `github.com/{owner}/{repo}` | 커밋, 릴리스/태그, 파일 트리, README | 변경 이벤트의 주 소스. 빈 레포 → 파일 등장이 가장 강한 신호 |
| `project_page` | GitHub/arXiv/HF가 아닌 일반 URL | 본문 텍스트, `<a href>` 목록 | "Code (coming soon)" 문구 사라짐, GitHub/HF 링크 신규 등장 |
| `arxiv` | `arxiv.org/abs/{id}` | abstract 페이지의 코드 링크, 버전 번호 | v2 등장, "Code" 탭 링크 추가 (Papers with Code 대체) |
| `huggingface` | `huggingface.co/{org}/{name}` | 레포 존재 여부, 파일 목록 | `*.safetensors`, `*.bin`, `*.pt`, `config.json` 등장 |

소스 단위 감지 결과는 Target 단위로 합쳐진다. 예: 페이지에서 GitHub 링크가 새로 나타나면 새 `github` 소스를 자동 추가하고 다음 주기부터 함께 감시한다.

&#91;embedded content: 추적 대상 상태 머신 · 5개 상태, 알림은 3개 전이에서만\]

`partial` 은 "코드는 나왔지만 가중치는 아직" 같은 흔한 중간 상태를 위한 것이다. Target마다 `wants` (관심 카테고리) 를 두되 기본값은 `docs_only` 를 제외한 모든 공개 카테고리로 한다. 따라서 코드, 모델, 데이터셋, 데모 각각이 처음 감지될 때마다 알림이 오고, `wants` 전부가 채워져야 `released` 로 넘어가 추적이 멈춘다. 특정 대상만 가중치에만 관심 있다면 `watch add --wants model_release` 로 좁힌다.

## 수집(Collector) 설계

모든 Collector는 같은 인터페이스를 구현하고, "이전 스냅샷과 지금의 차이"만 `ChangeEvent` 로 내보낸다. 원문 전체가 아니라 diff만 다음 단계로 넘기는 것이 LLM 비용을 낮추는 핵심이다.

```python
class Collector(Protocol):
    source_type: str
    def fetch(self, source: Source) -> Snapshot: ...
    def diff(self, prev: Snapshot | None, cur: Snapshot) -> list[ChangeEvent]: ...

@dataclass
class ChangeEvent:
    source_id: int
    kind: Literal["commit", "release", "file_added", "file_removed",
                  "page_text", "link_added", "hf_file_added", "repo_created"]
    summary: str          # 룰 필터와 LLM이 읽는 한 줄
    detail: str           # 커밋 메시지 본문, diff 발췌, 추가된 경로 등 (최대 2KB)
    url: str
    observed_at: datetime
```

**GitHub Collector**

- `GET /repos/{o}/{r}/commits?since={last_seen}` 로 신규 커밋만 받고, 커밋당 `GET /repos/{o}/{r}/commits/{sha}` 로 변경 파일 경로와 상태(added/modified)를 가져온다. 커밋이 50개를 넘으면 최신 50개만 상세 조회하고 나머지는 메시지만 쓴다.
- `GET /repos/{o}/{r}/releases/latest`, `/tags` 로 릴리스·태그 신규 여부를 본다.
- `GET /repos/{o}/{r}/git/trees/{default_branch}?recursive=1` 로 파일 트리를 받아 이전 트리와 집합 비교한다. 빈 저장소(README만)에 `*.py`, `requirements.txt`, `inference/`, `scripts/` 가 생기는 순간이 가장 중요한 신호이므로 커밋 메시지와 별개로 추적한다.
- README 본문의 `coming soon`, `TBD`, `TODO` 류 문구 소실도 `page_text` 이벤트로 낸다.
- `ETag` 를 저장해 `304 Not Modified` 응답은 rate limit을 소모하지 않게 한다.

**Project Page Collector**

- `httpx` + `trafilatura` (또는 `readability-lxml`)로 본문 텍스트를 추출하고, 모든 `<a href>` 를 정규화해 저장한다.
- 텍스트는 공백 정규화 후 `difflib.unified_diff` 로 비교하되, 변화율 2% 미만의 날짜·조회수류 노이즈는 무시한다.
- 신규 링크 중 `github.com`, `huggingface.co`, `arxiv.org` 도메인은 `link_added` 이벤트와 함께 새 Source 후보로 올린다.
- JS 렌더링이 필요한 페이지(React 기반 프로젝트 페이지)는 1차 범위에서 `requests` 기반으로 시도하고, 본문이 200자 미만이면 `needs_js` 플래그를 세워 Playwright 경로를 쓴다(2차).

**arXiv Collector**

- `export.arxiv.org/api/query?id_list={id}` 로 최신 버전 번호와 comment 필드("Code: https://..." 가 자주 들어감)를 본다.
- abs 페이지의 `Code, Data, Media` 섹션 링크를 함께 수집한다.

**Hugging Face Collector**

- `huggingface_hub.HfApi().list_repo_files()` 로 파일 목록을 받고 집합 비교한다. 레포가 없으면 `404` 를 "아직 없음"으로 기록하고, 등장 시 `repo_created` 이벤트를 낸다.
- 저자 org 이름만 알고 레포 이름을 모를 때는 `list_models(author=org, search=keyword)` 로 신규 모델을 탐색한다(P1).

**공통 규칙**

- 모든 HTTP 요청은 10초 타임아웃, 실패 시 지수 백오프 2회. 3회 연속 실패한 Source는 `error_count` 를 올리고 알림 없이 다음 주기로 넘긴다.
- 스냅샷 원문은 `snapshots` 테이블에 gzip 압축으로 저장하고, 각 Source당 최근 5개만 유지한다.

## 분류(Classifier) 설계

분류는 2단계다. 1차 룰 필터가 비용 없이 대부분을 거르고, 2차 LLM이 남은 변경 묶음을 카테고리와 신뢰도로 판정한다. 룰이 `strong` 으로 본 이벤트도 LLM을 거치되, LLM 실패 시 룰 결과를 fallback으로 쓴다.

**1차: 룰 필터**

| 신호 | 라벨 | 근거 |
| --- | --- | --- |
| 파일 추가: `*.safetensors`, `*.ckpt`, `*.pt`, `*.pth`, `*.bin`, `*.onnx`, `*.gguf` 또는 `config.json` + 가중치 | `strong` → `model_release` 후보 | 가중치 파일 자체 |
| 파일 추가: `inference.py`, `demo.py`, `app.py`, `serve*`, `gradio`, `Dockerfile`, `requirements.txt`, `setup.py`, `pyproject.toml` | `strong` → `inference_code` 후보 | 실행 가능한 코드의 등장 |
| 파일 추가: `train*.py`, `configs/*.yaml`, `scripts/train*` | `candidate` → `training_code` 후보 | 학습 코드 |
| 커밋 메시지에 `release`, `weights`, `checkpoint`, `pretrained`, `inference`, `demo`, `hf`, `v1.0`, `initial code` | `candidate` | 메시지 키워드 |
| 릴리스/태그 생성 | `candidate` | 공식 릴리스 |
| HF `repo_created` 또는 `hf_file_added` 중 가중치 확장자 | `strong` → `model_release` 후보 | HF 레포 등장 |
| 페이지에서 `coming soon` 소실 + GitHub/HF 링크 추가 | `candidate` | 공개 전환 신호 |
| 변경 파일이 `README*`, `docs/`, `*.md`, `LICENSE`, `.github/*`, `assets/*` 뿐 | `skip` → `docs_only` | 문서 수정 |
| 변경 없음 | `skip` | — |

룰 테이블은 `rules.yaml` 로 빼서 코드 수정 없이 패턴을 추가할 수 있게 한다.

**2차: LLM 분류**

- 모델: Claude Haiku 계열로 고정한다. 상위 모델 재질의는 두지 않고, 애매한 구간은 `needs_review` 로 기록해 사람이 본다. 픽스처 테스트 결과 재현율이 목표에 못 미치면 그때 재질의를 검토한다.
- 입력: Target 메타(제목, 논문 한 줄 요약, `wants`), 저장소 현재 파일 트리 요약(최대 80개 경로), 이번 주기의 `ChangeEvent` 목록(커밋 메시지 + 변경 경로, 최대 4KB).
- 출력: 아래 JSON 스키마만. 다른 텍스트는 거부하고 파싱 실패 시 1회 재시도.

```json
{
  "categories": [
    {"name": "model_release",  "confidence": 0.92, "evidence": ["ckpt/model.safetensors added", "README: 'Download weights'"]},
    {"name": "inference_code", "confidence": 0.85, "evidence": ["inference.py added"]}
  ],
  "release_state": "partial",
  "one_line": "가중치 1종과 추론 스크립트 공개, 학습 코드는 아직 없음",
  "notify": true
}
```

허용 카테고리: `model_release`, `inference_code`, `training_code`, `dataset`, `demo_space`, `docs_only`, `unrelated`.

**시스템 프롬프트 골자**

> 당신은 ML 연구 저장소의 변경 사항을 분류한다. 입력은 저장소 파일 트리와 최근 커밋/변경 목록이다. 사용자는 "모델 가중치"와 "실행 가능한 추론·배포 코드"가 실제로 공개되었는지만 알고 싶다. README에 "coming soon"이라고 쓰는 것은 공개가 아니다. 가중치 다운로드 링크, HF 레포 링크, 또는 실제 가중치 파일이 있어야 `model_release` 다. 각 판단에 파일 경로나 커밋 메시지 인용으로 근거를 붙여라. 확신이 없으면 confidence를 낮추고 `notify` 를 false로 두어라. JSON만 출력하라.

**알림 판정**

- `notify = true` 이고, `wants` (기본값: `docs_only` 제외 전 카테고리) 중 하나라도 `confidence ≥ 0.75` 이면 알림.
- 한 주기에 여러 카테고리가 동시에 통과하면 메시지 1건에 묶는다.
- `0.5 ≤ confidence < 0.75` 는 `needs_review` 로 기록하고 주간 다이제스트에만 포함.
- 같은 Target에서 같은 카테고리로 이미 알림을 보냈으면 상태 머신이 전이를 막아 재발송하지 않는다.

**평가**

- `fixtures/` 에 실제 공개 전후 저장소 10개의 커밋·트리 스냅샷을 저장해 회귀 테스트로 쓴다. 목표: 공개 이벤트 재현율 90% 이상, 문서 수정에 대한 오탐 5% 이하.

## 알림(Notifier) 설계

Slack Incoming Webhook 하나로 시작하고, 수신처는 개인 DM이다. 몇 주 운용해 오탐률을 확인한 뒤 팀 채널용 Webhook을 두 번째 Sink로 추가한다. 봇 토큰이나 앱 권한 설정 없이 URL 하나면 되고, 나중에 Slack App으로 바꿔도 메시지 빌더는 그대로 쓴다.

**메시지 포맷 (Block Kit)**

```
🟢 [모델 공개] HumanoidPolicy-X: Whole-body Manipulation via ...
가중치 1종과 추론 스크립트 공개, 학습 코드는 아직 없음

• model_release (0.92) — ckpt/model.safetensors added · README: "Download weights"
• inference_code (0.85) — inference.py added

상태: watching → partial   |   남은 관심: training_code
[GitHub]  [프로젝트 페이지]  [HF]  [이 대상 멈추기]
```

- 헤더 이모지는 전이 종류로 고정: `🟢` released, `🟡` partial, `🔵` needs\_review(다이제스트 전용).
- 근거(evidence)는 최대 3줄, 각 줄에 커밋/파일 링크를 건다.
- `[이 대상 멈추기]` 는 Webhook으로는 인터랙션이 불가하므로 1차에서는 `watch pause <id>` 명령어 텍스트로 대체한다.

**중복 억제**

- `notifications(target_id, category, sent_at)` 에 유니크 제약을 두어 같은 Target·카테고리 조합은 한 번만 보낸다.
- 한 주기 안에 여러 Target이 동시에 전이하면 메시지를 합쳐 1개로 보낸다(최대 5개, 초과는 "외 N건").
- 전송 실패는 `status = failed` 로 두고 다음 주기에 최대 3회 재시도한다.

**주간 다이제스트 (P2)**

- 매주 월요일 1회: 아직 `watching` 인 대상 수, 지난 7일 `needs_review` 목록, 180일 무변경으로 자동 `paused` 된 대상.

**이메일 (선택)**

- `SMTP_*` 환경변수가 있으면 Slack과 동일 내용을 텍스트 메일로도 보낸다. Notifier는 `Sink` 인터페이스 목록을 순회하므로 채널 추가는 클래스 하나 추가로 끝난다.

## 저장소 및 스키마

SQLite 파일 하나(`data/watcher.db`)에 5개 테이블을 둔다. 실행마다 변경분을 git에 커밋하므로 이력이 저절로 남고, 로컬로 옮길 때는 파일만 복사하면 된다. ORM 없이 `sqlite3` + 마이그레이션 스크립트(`migrations/001_init.sql`)로 간단하게 간다.

```sql
CREATE TABLE targets (
  id            INTEGER PRIMARY KEY,
  title         TEXT NOT NULL,
  origin_url    TEXT NOT NULL UNIQUE,       -- 사용자가 등록한 URL
  summary       TEXT,                       -- 논문 한 줄 요약 (LLM 컨텍스트용)
  wants         TEXT NOT NULL DEFAULT '["model_release","inference_code","training_code","dataset","demo_space"]',  -- JSON 배열
  state         TEXT NOT NULL DEFAULT 'new', -- new|watching|partial|released|paused
  created_at    TEXT NOT NULL,
  last_checked  TEXT,
  last_change   TEXT
);

CREATE TABLE sources (
  id            INTEGER PRIMARY KEY,
  target_id     INTEGER NOT NULL REFERENCES targets(id) ON DELETE CASCADE,
  type          TEXT NOT NULL,              -- github|project_page|arxiv|huggingface
  url           TEXT NOT NULL,
  meta          TEXT,                       -- JSON: owner/repo, default_branch, etag, hf_repo_type ...
  error_count   INTEGER NOT NULL DEFAULT 0,
  UNIQUE(target_id, url)
);

CREATE TABLE snapshots (
  id            INTEGER PRIMARY KEY,
  source_id     INTEGER NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
  taken_at      TEXT NOT NULL,
  kind          TEXT NOT NULL,              -- tree|readme|page_text|hf_files|commits_head
  content_hash  TEXT NOT NULL,
  content_gz    BLOB NOT NULL
);
CREATE INDEX idx_snapshots_source ON snapshots(source_id, kind, taken_at DESC);

CREATE TABLE events (
  id            INTEGER PRIMARY KEY,
  source_id     INTEGER NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
  observed_at   TEXT NOT NULL,
  kind          TEXT NOT NULL,
  summary       TEXT NOT NULL,
  detail        TEXT,
  url           TEXT,
  rule_label    TEXT NOT NULL,              -- skip|candidate|strong
  run_id        TEXT NOT NULL
);

CREATE TABLE classifications (
  id            INTEGER PRIMARY KEY,
  target_id     INTEGER NOT NULL REFERENCES targets(id) ON DELETE CASCADE,
  run_id        TEXT NOT NULL,
  model         TEXT NOT NULL,
  result_json   TEXT NOT NULL,              -- LLM 출력 원문
  decided_state TEXT NOT NULL,
  created_at    TEXT NOT NULL
);

CREATE TABLE notifications (
  id            INTEGER PRIMARY KEY,
  target_id     INTEGER NOT NULL REFERENCES targets(id) ON DELETE CASCADE,
  category      TEXT NOT NULL,
  channel       TEXT NOT NULL,              -- slack|email
  status        TEXT NOT NULL,              -- queued|sent|failed
  attempts      INTEGER NOT NULL DEFAULT 0,
  sent_at       TEXT,
  UNIQUE(target_id, category, channel)
);
```

**상태 전이 규칙**

| 현재 | 조건 | 다음 | 알림 |
| --- | --- | --- | --- |
| `new` | 첫 스냅샷 저장 완료 | `watching` | 없음 |
| `watching` | `wants` 중 일부 카테고리만 임계값 통과 | `partial` | 있음 |
| `watching` | `wants` 전부 통과 | `released` | 있음 (1건으로 합침) |
| `partial` | 남은 `wants` 카테고리 통과 | `released` | 있음 |
| `watching`/`partial` | `docs_only` 또는 변경 없음 | 유지 | 없음 |
| `watching`/`partial` | 180일 무변경 또는 `watch pause` | `paused` | 없음 (다이제스트에만) |
| `paused` | `watch resume` | `watching` | 없음 |
| `released` | — | 종료, 수집 중단 | — |

**보존 정책**

- `snapshots` 는 Source·kind당 최근 5개만 유지, 나머지는 실행 종료 시 삭제 후 `VACUUM`.
- `events` 는 180일 보존. `classifications`, `notifications` 는 전체 보존(용량이 작다).

## 스케줄링 및 배포

GitHub Actions의 `schedule` 트리거로 하루 2회 실행하고, 상태 DB를 같은 저장소에 커밋한다. 서버 없이 무료로 돌아가고, 저장소를 private으로 두면 추적 목록도 외부에 노출되지 않는다.

```yaml
# .github/workflows/watch.yml
name: release-watch
on:
  schedule:
    - cron: "0 0,12 * * *"      # UTC 00:00, 12:00 = KST 09:00, 21:00
  workflow_dispatch:
    inputs:
      target: { description: "특정 target id만 실행", required: false }

permissions:
  contents: write

jobs:
  run:
    runs-on: ubuntu-latest
    timeout-minutes: 10
    concurrency: { group: watch, cancel-in-progress: false }
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: "3.12", cache: pip }
      - run: pip install -e .
      - run: watch run ${{ inputs.target && format('--target {0}', inputs.target) || '' }}
        env:
          GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
          ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
          SLACK_WEBHOOK_URL: ${{ secrets.SLACK_WEBHOOK_URL }}
          HF_TOKEN: ${{ secrets.HF_TOKEN }}
      - name: Commit state
        run: |
          git config user.name watcher-bot
          git config user.email bot@users.noreply.github.com
          git add data/watcher.db
          git diff --cached --quiet || git commit -m "state: $(date -u +%F-%H%M)"
          git push
```

**시크릿**

| 이름 | 용도 | 필수 |
| --- | --- | --- |
| `GITHUB_TOKEN` | Actions 기본 토큰. 공개 저장소 조회에 충분(5,000 req/h) | 자동 제공 |
| `ANTHROPIC_API_KEY` | LLM 분류 | 예 |
| `SLACK_WEBHOOK_URL` | 알림 | 예 |
| `HF_TOKEN` | HF API rate limit 완화, gated 레포 조회 | 선택 |

**비용 추정 (대상 100개 기준)**

- GitHub API: 대상당 평균 4 req × 100 × 2회 = 800 req/일. 한도의 10% 미만.
- LLM: 하루 변경이 있는 대상은 보통 5개 미만. 입력 5K 토큰 × 5회 × Haiku 단가 ≈ 수 센트/일.
- Actions: 실행당 3\~5분 × 2회 × 30일 ≈ 300분/월. 무료 2,000분 안.

**로컬 대안**

- 동일 CLI를 `crontab -e` 에 `0 9,21 * * * cd ~/release-watcher && .venv/bin/watch run` 로 등록하면 그대로 동작한다. DB 커밋 단계만 생략된다.
- 두 환경을 동시에 쓰지 않는다. DB 충돌을 피하려면 한 곳만 `run` 하고 다른 곳은 `watch list` 조회만 한다.

**주의**

- Actions `schedule` 은 수 분\~수십 분 지연될 수 있고, 저장소에 60일간 커밋이 없으면 자동 비활성화된다. 상태 DB 커밋이 매일 발생하므로 실제로는 문제되지 않는다.
- 봇 커밋이 다시 워크플로를 트리거하지 않도록 `on: push` 는 두지 않는다.

## 프로젝트 구조 및 CLI

Python 3.12, 단일 패키지 `release_watcher`, 의존성은 `httpx`, `trafilatura`, `huggingface_hub`, `anthropic`, `typer`, `pyyaml` 여섯 개로 제한한다.

```
release-watcher/
├── pyproject.toml              # [project.scripts] watch = "release_watcher.cli:app"
├── rules.yaml                  # 룰 필터 패턴 (코드 수정 없이 편집)
├── data/
│   └── watcher.db              # SQLite 상태 (git 추적)
├── migrations/
│   └── 001_init.sql
├── release_watcher/
│   ├── cli.py                  # typer 앱: add / list / show / run / pause / resume / remove
│   ├── config.py               # 환경변수, 임계값, 경로
│   ├── db.py                   # 연결, 마이그레이션, 리포지토리 함수
│   ├── models.py               # Target / Source / Snapshot / ChangeEvent dataclass
│   ├── resolver.py             # URL → 소스 타입 판별, 페이지에서 링크 추출
│   ├── collectors/
│   │   ├── base.py
│   │   ├── github.py
│   │   ├── project_page.py
│   │   ├── arxiv.py
│   │   └── huggingface.py
│   ├── classify/
│   │   ├── rules.py            # rules.yaml 로드 + 라벨링
│   │   ├── llm.py              # 프롬프트 구성, JSON 파싱, 재시도
│   │   └── prompts/system.md
│   ├── state.py                # 상태 머신 전이
│   ├── notify/
│   │   ├── base.py             # Sink 인터페이스
│   │   ├── slack.py
│   │   └── email.py
│   └── runner.py               # run 한 주기의 오케스트레이션
├── tests/
│   ├── fixtures/               # 공개 전후 저장소 스냅샷 10세트
│   ├── test_rules.py
│   ├── test_state.py
│   └── test_collectors.py      # respx 로 HTTP 모킹
└── .github/workflows/watch.yml
```

**CLI**

| 명령 | 동작 |
| --- | --- |
| `watch add <url> [--title T] [--wants model_release,...]` | URL 타입 판별 → Target 생성 → 페이지에서 연관 소스 추출 → 첫 스냅샷 저장. `--wants` 생략 시 전 카테고리 |
| `watch add --from tabs.txt` | 한 줄에 URL 하나인 파일을 읽어 일괄 등록. 중복 URL은 건너뛰고, 이미 공개된 대상은 `released` 로 바로 둔다 |
| `watch list [--state watching]` | 대상 목록: id, 제목, 상태, 마지막 확인, 소스 수 |
| `watch show <id>` | 소스 목록, 최근 이벤트 20건, 분류 이력 |
| `watch run [--target ID] [--dry-run] [--no-notify]` | 한 주기 실행. `--dry-run` 은 DB 쓰기와 알림 없이 분류 결과만 출력 |
| `watch pause <id>` / `watch resume <id>` | 상태 전이 |
| `watch remove <id>` | 대상과 하위 데이터 삭제 |
| `watch replay <id> --since 2026-10-01` | 저장된 이벤트로 분류기만 재실행 (프롬프트 튜닝용) |

**북마클릿**

크롬 북마크 바에 두는 한 줄 JavaScript로, 현재 탭 URL을 GitHub `workflow_dispatch` API에 `url` 입력으로 보낸다. 워크플로가 `watch add $url` 을 실행하고 결과를 Slack DM으로 돌려준다. 북마클릿 안에 `repo` 스코프 fine-grained PAT가 들어가므로 저장소는 private, PAT는 해당 저장소 `actions:write` 만 허용한다.

```javascript
javascript:(()=>{fetch('https://api.github.com/repos/OWNER/release-watcher/actions/workflows/add.yml/dispatches',{method:'POST',headers:{Authorization:'Bearer PAT',Accept:'application/vnd.github+json'},body:JSON.stringify({ref:'main',inputs:{url:location.href}})}).then(r=>alert(r.ok?'등록 요청됨':'실패 '+r.status))})();
```

**기존 탭 일괄 등록**

크롬에서 `탭 전체 북마크` → 북마크 관리자에서 HTML 내보내기 → `grep -o 'HREF="[^"]*"' bookmarks.html | cut -d'"' -f2 > tabs.txt` → `watch add --from tabs.txt`. 또는 OneTab 등 탭 관리 확장의 "URL 내보내기"를 그대로 쓴다.

**설정 (`config.py`, 환경변수 우선)**

```toml
[thresholds]
notify_confidence = 0.75
review_confidence = 0.50
auto_pause_days   = 180

[llm]
model          = "claude-haiku-4-5"
escalate_model = ""              # 비우면 재질의 안 함
max_input_kb   = 4

[collect]
max_commit_detail = 50
http_timeout_s    = 10
```

`watch add` 는 등록 직후 `--dry-run` 과 같은 1회 분류를 실행해 "현재 이미 공개된 상태"면 바로 `released` 로 두고 알리지 않는다. 이미 공개된 것을 등록해 놓고 영원히 알림을 기다리는 일을 막기 위해서다.

## 구현 로드맵 (Claude Code 작업 단위)

각 단계는 Claude Code 세션 하나에서 끝나는 크기로 자르고, 완료 조건은 테스트 또는 실제 명령 실행으로 확인한다. 1\~4단계가 끝나면 GitHub 소스 하나짜리 대상에 대해 end-to-end 알림이 온다.

| 단계 | 작업 | 완료 조건 |
| --- | --- | --- |
| 1 | 패키지 뼈대, `pyproject.toml`, `db.py` + `001_init.sql`, `models.py`, `watch add/list/show/remove`, `watch add --from` | `watch add https://github.com/x/y` 후 `watch list` 에 표시. `tabs.txt` 20줄 일괄 등록 성공. `pytest tests/test_state.py` 통과 |
| 2 | `collectors/github.py`: 커밋·트리·릴리스 수집, ETag, 스냅샷 저장 및 diff | respx 픽스처로 "빈 레포 → 코드 추가" 시 `file_added` 이벤트 생성 테스트 통과 |
| 3 | `classify/rules.py` + `rules.yaml`, `state.py` | 픽스처 10세트에서 룰만으로 `strong/candidate/skip` 라벨 기대값 일치 |
| 4 | `classify/llm.py` (Haiku), 프롬프트, JSON 스키마 검증, `notify/slack.py` (DM), `runner.py`, `watch run --dry-run` | 실제 테스트 레포에 가중치 파일 커밋 → Slack DM 1건 수신. 두 번째 실행에서 재발송 없음 |
| 5 | `.github/workflows/watch.yml`, DB 커밋 단계, 시크릿 설정 | 수동 `workflow_dispatch` 성공, `data/watcher.db` 봇 커밋 확인 |
| 6 | `.github/workflows/add.yml` + 북마클릿, 등록 결과 Slack DM 회신 | 크롬에서 북마클릿 1회 클릭 → 30초 내 "등록됨" DM 수신 |
| 7 | `collectors/project_page.py`, `resolver.py`: 페이지에서 GitHub/HF/arXiv 링크 추출, 자동 Source 추가 | 프로젝트 페이지 URL 하나로 `watch add` → 소스 2개 이상 자동 등록 |
| 8 | `collectors/huggingface.py`, `collectors/arxiv.py` | HF 레포 생성 픽스처에서 `repo_created` → `model_release` 알림 |
| 9 | `watch replay`, 평가 스크립트, 임계값 튜닝 | 재현율 ≥ 90%, 오탐 ≤ 5% 수치 기록. 미달 시 상위 모델 재질의 도입 여부 결정 |
| 10 | 팀 채널 Sink 추가, 주간 다이제스트, 180일 자동 pause, 이메일 Sink | 채널에 알림 1건 수신, 월요일 cron에서 다이제스트 1건 수신 |

**Claude Code에 넘길 때**

- 이 문서를 저장소 루트에 `docs/DESIGN.md` 로 두고 `CLAUDE.md` 에서 참조하게 한다. 단계별로 "N단계를 구현하고 완료 조건을 확인해줘"로 요청한다.
- `CLAUDE.md` 에 넣을 규칙: 의존성 6개 외 추가 금지, 모든 HTTP는 `httpx` 와 타임아웃 필수, LLM 호출은 `classify/llm.py` 에서만, 테스트는 네트워크 없이 통과해야 함.
- 2단계부터는 실제 공개 전후가 기록된 저장소(예: 최근 공개된 로보틱스 VLA 모델 레포)의 커밋 이력을 `fixtures/` 로 미리 떠 두면 Claude Code가 룰과 프롬프트를 실제 데이터로 검증할 수 있다.

## 리스크 및 결정 사항

**리스크**

| 리스크 | 영향 | 대응 |
| --- | --- | --- |
| 저자가 코드를 새 저장소에 올리고 원래 레포는 그대로 둠 | 감지 실패 | 프로젝트 페이지·arXiv 링크 변화를 함께 감시, 저자 GitHub 계정의 신규 공개 레포 탐색(P2) |
| JS 렌더링 페이지에서 본문 추출 실패 | 페이지 소스 무용 | `needs_js` 플래그 + Playwright 경로, 또는 GitHub/HF 소스만으로 운용 |
| 가중치가 Google Drive·Dropbox 링크로만 공개 | 파일 확장자 룰 미작동 | README에 추가된 외부 링크 도메인 룰 + LLM 판단에 의존 |
| LLM이 `coming soon` 문구를 공개로 오판 | 오탐 알림 | 프롬프트에 부정 예시 명시, 임계값 0.75, evidence 필수 |
| GitHub Actions 지연·비활성화 | 알림 지연 | 매일 DB 커밋으로 활성 유지, 중요 대상은 로컬 cron 병행 가능 |
| 추적 대상이 수백 개로 늘어남 | 실행 시간 초과 | Source별 병렬 수집(`asyncio`), `released`/`paused` 는 수집 제외 |

**결정 사항 (2026-10-17)**

| 질문 | 결정 | 반영 위치 |
| --- | --- | --- |
| 알림 채널 | Slack DM으로 먼저 개발·검증, 이후 팀 채널 공유 | 알림 설계, F12, 로드맵 10단계 |
| `wants` 기본값 | 모든 공개 카테고리에서 각각 알림 (`docs_only` 제외) | 추적 대상 모델링, 알림 판정, 스키마 기본값 |
| 분류 모델 | Haiku 고정, 재질의 없음. 테스트 후 재검토 | 분류 설계, 로드맵 9단계 |
| 등록 수단 | 북마클릿으로 시작 | F10, CLI 섹션, 로드맵 6단계 |
| 기존 탭 일괄 등록 | 필요 → `watch add --from tabs.txt` | F11, CLI 섹션, 로드맵 1단계 |
