# Remote Agent 실행 절차서 (v3 · MCP push 전용)

## v3 가 바뀐 점

v2 에서 `gh` CLI 로 workflow dispatch 와 파일 업로드를 하려 했지만 **sandbox 에 `gh` 바이너리가 없다**. 대신 환경에 **GitHub MCP integration** 이 있으므로 그 도구로만 원격 쓰기를 수행한다.

| v2 가정 | v3 실제 |
|---------|---------|
| `gh workflow run publish.yml` | 없음 (publish.yml 삭제) |
| `scripts/upload_files.py` (gh 래퍼) | 사용 안 함, MCP `push_files` 사용 |
| `git push origin main` | 사용 안 함 (claude.ai proxy read-only) |

## 환경 제약 (확정)

| 가능 | 불가 |
|------|------|
| `git clone` / `git pull` | `git push` (모든 경로) |
| Python, pip install | `gh` CLI |
| PlayMCP (카카오톡) | |
| GitHub MCP (push_files, create_or_update_file, get_file_contents 등) | |
| 외부 호스트 접근: github.com, api.github.com, pypi.org | 한국 뉴스 호스트 |

## 아키텍처

```
Actions collect.yml (cron 06:55/17:55 KST)
  → RSS 6개 수집 → state/candidates.json 커밋
         ↓
Remote agent (cron 07:00/18:00 KST)
  → clone · git pull
  → prepare-run  (로컬 state.json 수정)
  → grounded 분석 → state/analyzed.json (로컬)
  → render → docs/index.html + archive/YYYY-MM-DD-HHMM.html (로컬)
  → mark-success → state/state.json pipeline_status=completed (로컬)
  → GitHub MCP push_files 로 4개 파일을 단일 커밋으로 원격 푸시
       · docs/index.html, archive/...html, state/state.json, state/analyzed.json
  → 카카오 MCP 로 성공 메시지 전송
```

## 전제

- working directory 에 저장소 clone 됨
- `git config user.email`, `user.name` 이미 설정됨 (안 됐으면 설정)
- `pip install --user --break-system-packages -r requirements.txt`
- `TZ=Asia/Seoul` 환경변수 설정

## 단계별 절차

### 단계 A — 준비

```bash
cd $(git rev-parse --show-toplevel 2>/dev/null || pwd)
git config user.email "helen1356@naver.com" 2>/dev/null || true
git config user.name "helen13566-netizen" 2>/dev/null || true
pip install --user --break-system-packages -r requirements.txt >/dev/null 2>&1 || true
export TZ=Asia/Seoul
```

### 단계 B — prepare-run

```bash
python3 -m pipeline.run prepare-run --period "$PERIOD"
```

stdout JSON 에서 `issue_number`, `generation_timestamp`, `next_run_time` 을 기억.

### 단계 C — candidates.json 동기화

Actions `collect.yml` 이 cron 에 따라 이미 `state/candidates.json` 을 commit 해 놓았다(매일 06:55 / 17:55 KST). 이 파일을 받아온다:

```bash
git pull --ff-only origin main || {
  # 로컬 변경이 있어 merge 실패 시 reset
  git fetch origin main
  git reset --hard origin/main
  git pull --ff-only origin main
}
ls -la state/candidates.json
```

`candidates.json` 이 **최근 60분 이내**에 갱신되지 않았으면(= collect cron 이 누락되었을 가능성) **실패 처리**(`FAILED_STAGE=collecting`).

확인:
```bash
CANDIDATES_MTIME_EPOCH=$(stat -c %Y state/candidates.json)
NOW_EPOCH=$(date +%s)
AGE_MIN=$(( (NOW_EPOCH - CANDIDATES_MTIME_EPOCH) / 60 ))
if [ "$AGE_MIN" -gt 60 ]; then
  FAILED_STAGE=collecting
  ERROR_REASON="candidates.json 이 ${AGE_MIN}분 전에 마지막으로 갱신됨 (Actions collect cron 누락 의심)"
fi
```

### 단계 D — grounded 분석

`state/candidates.json` 을 읽어 각 기사에 5개 필드를 덧붙인 `state/analyzed.json` 을 작성한다.

#### 🔒 절대 제약

- `ai_summary` / `extraction_reason` 은 해당 기사의 `title` + `content_text` 범위 안에서만. 원문에 없는 사실·숫자·인용·해석 금지.
- 원문이 부실해 의미 있는 요약을 만들 수 없으면 제외.

#### 출력 schema

```json
{
  "issue_number": <prepare-run 의 issue_number>,
  "generation_timestamp": <prepare-run 의 generation_timestamp>,
  "trend_hashtags": ["...", ...],     // 3~8 개, # 접두사 없는 문자열
  "articles": [
    {
      "article_id": "...", "title": "...", "source": "...",
      "published_at": "...", "original_url": "...",
      "content_text": "...", "category": "ai_news|general_news",
      "keywords": [...],
      "ai_summary": "<140~220자 grounded>",
      "extraction_reason": "<40~80자>",
      "relevance_score": <0-10 float>,
      "is_must_know": <score >= 8.0>
    }
  ]
}
```

#### 점수 산정 — 인생중요뉴스 5차원 (최고값 채택)

1. 경제/생계  2. 안전/건강  3. 정책/법제  4. 기술/일자리  5. 국제정세

루머·가십·연예·스포츠 결과는 최대 4점.

#### 분량 제약

- 최소 3건 (미달 시 `FAILED_STAGE=analyzing`)
- 최대 30건 (초과 시 `relevance_score` 상위 30건만)

#### 파일 쓰기

```bash
python3 - <<'PY'
import json, pathlib
analyzed = { ... 당신이 구성한 dict ... }
pathlib.Path("state/analyzed.json").write_text(
    json.dumps(analyzed, ensure_ascii=False, indent=2), encoding="utf-8"
)
PY
```

`mark-stage`:
```bash
python3 -m pipeline.run mark-stage --stage analyzing
```

### 단계 E — render (로컬)

```bash
python3 -m pipeline.run render
python3 -m pipeline.run mark-success
```

render 성공 시 로컬에 다음 파일들이 갱신된다:
- `docs/index.html` (덮어쓰기)
- `archive/YYYY-MM-DD-HHMM.html` (신규)
- `state/state.json` (pipeline_status=completed, retry_count=0, last_success_at 등)

### 단계 F — GitHub MCP 로 원격 push (핵심)

**도구**: GitHub MCP integration 의 **`push_files`** (여러 파일 단일 커밋) 를 우선 사용한다. 없으면 `create_or_update_file` 을 파일별로 4회 호출한다.

커밋 대상 4개 파일 (archive 는 이번 실행의 파일명 하나):
- `docs/index.html`
- `archive/<YYYY-MM-DD-HHMM>.html`
- `state/state.json`
- `state/analyzed.json`

**`push_files` 호출 예** (도구 스펙에 따라 조정):
```
owner: helen13566-netizen
repo: 002-daily-news
branch: main
message: "news: ISSUE #${ISSUE_NUMBER} ${PERIOD} 브리핑 $(date +%Y-%m-%d_%H:%M)"
files: [
  {"path": "docs/index.html", "content": <본문 문자열>},
  {"path": "archive/2026-04-19-0700.html", "content": <본문>},
  {"path": "state/state.json", "content": <본문>},
  {"path": "state/analyzed.json", "content": <본문>}
]
```

각 파일의 `content` 는 UTF-8 텍스트. 필요한 경우 base64 인코딩 (도구 스펙 확인).

#### 권한 문제 시

`push_files` 또는 `create_or_update_file` 이 **403 "Resource not accessible by integration"** 을 리턴하면 → GitHub MCP integration 에 `contents:write` 권한이 없는 것. 이 경우:

1. `FAILED_STAGE=deploying`, `ERROR_REASON="GitHub MCP 403 contents:write 권한 없음"` 으로 기록
2. 단계 X 로 분기

#### 재시도

MCP push 실패 시 3회 재시도, 간격 5s / 10s / 20s. 3회 모두 실패 시 단계 X.

### 단계 G — 카카오 성공 알림

```bash
python3 -m pipeline.run mark-stage --stage notifying
SUCCESS_MSG=$(python3 -m pipeline.run notify-success)
echo "=== 전송할 메시지 ==="
echo "$SUCCESS_MSG"
```

PlayMCP 카카오톡 도구 호출:

```
도구: mcp__claude_ai_PlayMCP__KakaotalkChat-MemoChat
인자: text=<SUCCESS_MSG 전체, 수정·요약 금지>
```

**MCP 응답을 stdout 에 그대로 기록하라** — 성공/실패 여부를 사후 검증하기 위해. (이전 실행에서 전송 "성공" 반환이 실제 카카오톡 수신으로 이어졌는지 확인 필요했음.)

3회 재시도. 파이프라인 자체는 이미 성공이므로 MCP 실패해도 종료 상태는 completed.

### 단계 H — 종료 보고

stdout 마지막에 JSON 한 줄:

```json
{"status": "completed", "issue_number": N, "article_count": N, "failed_stage": null, "kakao_message": "<전체>", "mcp_kakao_response": "<MCP 응답 원문>", "duration_seconds": N}
```

---

## 단계 X — 실패 처리

어디서든 `FAILED_STAGE` 세팅되면:

```bash
python3 -m pipeline.run mark-failure --stage "$FAILED_STAGE" --reason "$ERROR_REASON"

# state.json 만 MCP 로 push (docs 는 이전 성공본 보존)
# GitHub MCP create_or_update_file 로 state/state.json 업로드
```

`create_or_update_file`:
```
owner: helen13566-netizen
repo: 002-daily-news
branch: main
path: state/state.json
content: <state.json 내용>
message: "state: failure at ${FAILED_STAGE} (ISSUE #${ISSUE_NUMBER} ${PERIOD})"
```

state 업로드마저 실패해도 무시하고 카카오 알림은 전송:

```bash
FAILURE_MSG=$(python3 -m pipeline.run notify-failure)
```

카카오 MCP 로 `FAILURE_MSG` 전체 전송. 그리고 stdout JSON:

```json
{"status": "failed", "failed_stage": "...", "error_reason": "...", "kakao_message": "<FAILURE_MSG>", "mcp_kakao_response": "...", ...}
```

종료 코드 0.

---

## 체크리스트 (종료 전 자기 검증)

- [ ] analyzed.json 의 모든 `ai_summary` / `extraction_reason` 이 원문 범위 내
- [ ] `is_must_know=true` 기사들 `relevance_score` ≥ 8.0
- [ ] `trend_hashtags` 3~8 개
- [ ] issue_number 가 prepare-run / state.json / analyzed.json 에서 일치
- [ ] 성공 시: GitHub MCP push_files 응답이 200 OK, 새 commit SHA 반환 확인
- [ ] 카카오 MCP 응답 원문을 stdout 에 기록했는지
- [ ] 카카오 메시지가 정확한 템플릿으로 시작하는지

## 한눈에

```
(환경) → prepare-run → git pull (candidates.json) → grounded 분석
      → render → mark-success → GitHub MCP push_files (4 files, single commit)
      → 카카오 MCP notify-success → 종료

(실패 시) mark-failure → MCP create_or_update_file (state.json만)
      → 카카오 MCP notify-failure → 종료
```
