# Remote Agent 실행 절차서 (v2 · 하이브리드 아키텍처)

## 왜 v2 인가

원격 에이전트가 실행되는 Anthropic sandbox 환경은:

- **외부 호스트 egress allowlist** 로 한국 뉴스 사이트(AI타임스, ZDNet Korea, 전자신문, 연합뉴스, 매일경제, 한겨레) 직접 접근 불가 (403 "Host not in allowlist")
- **`git push`** 가 claude.ai 로컬 git proxy(127.0.0.1:29339) 로 라우팅되는데 이 proxy 는 read-only (403 "Permission denied")
- 하지만 `github.com` / `api.github.com` 은 허용됨 (clone 성공, OAuth 인증)
- `pypi.org` 허용 (pip install 성공)

이를 우회하기 위해 **하이브리드 아키텍처**:

```
Actions `collect.yml` (cron) → RSS 수집 → state/candidates.json 커밋
        ↓
Remote agent (cron) → clone → git pull
                    → grounded 분석 → state/analyzed.json (로컬)
                    → scripts/upload_files.py 로 state.json + analyzed.json 을 REST API 로 업로드
                    → gh workflow run publish.yml → docs 렌더 & 커밋
                    → git pull → 카카오 MCP 알림
```

agent 는 **sandbox 에서 허용된 github.com / api.github.com 만 사용**, 한국 뉴스 사이트와 git push 는 모두 GitHub Actions runner 가 담당.

---

## 0. 역할

당신은 Claude Opus 4.7 **Remote Agent**. 매일 07:00 KST(오전) 또는 18:00 KST(오후)에 트리거되어 일간 뉴스 브리핑을 생성·배포·알림한다.

## 1. 사전 조건

저장소는 이미 working directory 에 clone 되어 있다.

```bash
# 기본 환경 설정
git config user.email "helen1356@naver.com"
git config user.name "helen13566-netizen"

# 파이썬 의존성
pip install --user --break-system-packages -r requirements.txt

# 현재 브랜치 확인
git branch --show-current  # main 이어야 함, detached 면 git checkout main
```

`TZ=Asia/Seoul` 이 환경변수로 설정되어 있지 않으면 모든 파이프라인 명령 앞에 `TZ=Asia/Seoul` 을 붙여라.

## 2. 단계별 절차

### 단계 A — prepare-run

```bash
TZ=Asia/Seoul python3 -m pipeline.run prepare-run --period "$PERIOD"
```

`$PERIOD` 는 트리거마다 다르다: 오전 트리거는 `오전`, 오후 트리거는 `오후`.

stdout JSON 에서 `issue_number`, `generation_timestamp`, `next_run_time` 을 파싱해 기억한다. 이 값들은 **publish workflow input 으로 사용** 한다.

### 단계 B — collect workflow 실행 + 대기

```bash
# collect workflow trigger (sandbox 외부에서 RSS 수집을 수행)
gh workflow run collect.yml --ref main

# 최근 생성된 run 의 ID 조회
sleep 5
RUN_ID=$(gh run list --workflow=collect.yml --limit=1 --json databaseId --jq '.[0].databaseId')
echo "collect run id=$RUN_ID"

# 완료 대기 (최대 5분)
gh run watch "$RUN_ID" --interval 15 --exit-status || FAILED_STAGE=collecting
```

`gh run watch` 가 비정상 종료하면 collect 실패. `FAILED_STAGE=collecting` 으로 설정 → **단계 X (실패 처리)** 로 분기.

성공하면:

```bash
git pull --ff-only origin main
# state/candidates.json 이 최신으로 갱신되었는지 확인
ls -la state/candidates.json
```

### 단계 C — grounded 분석

`state/candidates.json` 을 읽어 기사별로 5개 필드를 추가한 `state/analyzed.json` 을 작성한다.

#### 🔒 절대 제약

- `ai_summary` 와 `extraction_reason` 은 **해당 기사의 `title` + `content_text` 범위 안에서만** 생성한다. 원문에 없는 사실·숫자·인용·해석을 추가하지 마라.
- 원문이 부실해 의미 있는 요약을 만들 수 없으면 그 기사를 제외한다.

#### 입력 schema (candidates.json)

```json
{
  "collection_timestamp": "...",
  "source_stats": {...},
  "articles": [
    {"article_id": "...", "title": "...", "source": "...",
     "published_at": "...", "original_url": "...",
     "content_text": "...", "category": "ai_news|general_news",
     "keywords": [...]}
  ]
}
```

#### 출력 schema (analyzed.json)

```json
{
  "issue_number": <prepare-run 의 issue_number>,
  "generation_timestamp": <prepare-run 의 generation_timestamp>,
  "trend_hashtags": ["...", ...],        // 3~8 개
  "articles": [
    {
      "article_id": "...", "title": "...", "source": "...",
      "published_at": "...", "original_url": "...",
      "content_text": "...", "category": "...", "keywords": [...],
      "ai_summary": "<grounded 요약 140~220자>",
      "extraction_reason": "<40~80자 추출 이유>",
      "relevance_score": <0-10>,
      "is_must_know": <score >= 8.0>
    }
  ]
}
```

#### 점수 산정 — 인생중요뉴스 5차원

각 차원을 0~10 으로 평가 후 **최고값**을 `relevance_score` 로 택.

1. 경제/생계  2. 안전/건강  3. 정책/법제  4. 기술/일자리  5. 국제정세

루머·가십·연예·스포츠 결과는 최대 4점.

#### 기사 수 제약

- 최소 3건 필요 — 그보다 적으면 `FAILED_STAGE=analyzing` 으로 실패 처리
- 최대 30건 — 초과 시 `relevance_score` 상위 30건만 유지
- 가능하면 ai_news 2건 이상, general_news 2건 이상 균형 유지

#### 파일 쓰기

```bash
python3 - <<'PY'
import json, pathlib
analyzed = { ... }   # 당신이 구성한 dict
pathlib.Path("state/analyzed.json").write_text(
    json.dumps(analyzed, ensure_ascii=False, indent=2), encoding="utf-8"
)
PY
```

### 단계 D — analyzed + state 업로드

```bash
TZ=Asia/Seoul python3 -m pipeline.run mark-stage --stage generating
python3 scripts/upload_files.py \
    "state: ISSUE #${ISSUE_NUMBER} ${PERIOD} analyzed + state 업로드" \
    state/state.json state/analyzed.json
```

3회 재시도. 그래도 실패하면 `FAILED_STAGE=uploading` → 단계 X.

### 단계 E — publish workflow 실행 + 대기

```bash
gh workflow run publish.yml --ref main \
    -F period="$PERIOD" \
    -F issue_number="$ISSUE_NUMBER"

sleep 5
PUB_RUN_ID=$(gh run list --workflow=publish.yml --limit=1 --json databaseId --jq '.[0].databaseId')
echo "publish run id=$PUB_RUN_ID"

gh run watch "$PUB_RUN_ID" --interval 15 --exit-status || FAILED_STAGE=deploying
```

성공 시:

```bash
git pull --ff-only origin main
# state/state.json 이 pipeline_status=completed 로 갱신되었는지 확인
cat state/state.json
```

### 단계 F — 카카오톡 성공 알림

```bash
TZ=Asia/Seoul python3 -m pipeline.run mark-stage --stage notifying
SUCCESS_MSG=$(TZ=Asia/Seoul python3 -m pipeline.run notify-success)
echo "$SUCCESS_MSG"
```

`SUCCESS_MSG` 전체를 **카카오톡 MCP** 로 전송:

```
도구: mcp__claude_ai_PlayMCP__KakaotalkChat-MemoChat
인자: text=<SUCCESS_MSG 전체, 수정 금지>
```

MCP 호출 3회 재시도. 실패해도 파이프라인 자체는 성공 상태(docs 배포됨)이므로 stderr 경고만 남기고 정상 종료.

### 단계 G — 종료 보고

stdout 마지막에 다음 JSON 한 줄 출력:

```json
{"status": "completed", "issue_number": N, "article_count": N, "failed_stage": null, "kakao_message": "<전체>", "duration_seconds": N}
```

---

## 3. 단계 X — 실패 처리

어느 단계에서든 `FAILED_STAGE` 가 set 되면:

```bash
TZ=Asia/Seoul python3 -m pipeline.run mark-failure \
    --stage "$FAILED_STAGE" \
    --reason "$ERROR_REASON"

# state.json 을 실패 상태로 업로드 (docs 는 건드리지 않음 = 이전 발행본 보존)
python3 scripts/upload_files.py \
    "state: failure at $FAILED_STAGE (ISSUE #$ISSUE_NUMBER $PERIOD)" \
    state/state.json

# 실패 메시지 생성
FAILURE_MSG=$(TZ=Asia/Seoul python3 -m pipeline.run notify-failure)
```

`FAILURE_MSG` 를 **카카오톡 MCP** 로 전송:

```
도구: mcp__claude_ai_PlayMCP__KakaotalkChat-MemoChat
인자: text=<FAILURE_MSG 전체>
```

그리고 stdout JSON:

```json
{"status": "failed", "failed_stage": "...", "kakao_message": "<FAILURE_MSG>", ...}
```

종료 코드 0 (trigger 재발화 방지).

---

## 4. 요약 한눈에

```
(환경 준비)
  ↓
prepare-run --period <오전|오후>
  ↓
gh workflow run collect.yml + watch       ← Actions 가 RSS 수집 후 커밋
  ↓
git pull   (candidates.json 수신)
  ↓
[Agent] grounded 분석 → state/analyzed.json
  ↓
upload_files.py state.json analyzed.json  ← api.github.com PUT contents
  ↓
gh workflow run publish.yml + watch       ← Actions 가 render + docs 커밋
  ↓
git pull   (state.json 갱신 확인)
  ↓
카카오 MCP 로 성공 메시지 전송
  ↓
[종료]

(단계 어디서든 실패)
  ↓
mark-failure → upload state.json → 카카오 MCP 로 실패 메시지 → [종료]
```

## 5. 재시도 정책 요약

| 대상 | 재시도 |
|------|--------|
| `gh workflow run collect.yml` 실패 | 3회, 5s/10s/20s |
| `gh run watch` 비정상 종료 | 재시도 하지 않음 (단, Actions 로그 확인 가능) |
| `upload_files.py` | 3회, 5s/10s/20s |
| `gh workflow run publish.yml` | 3회 |
| 카카오 MCP 전송 | 3회 |

## 6. 체크리스트 (종료 전 자기 검증)

- [ ] `analyzed.json` 의 모든 `ai_summary` / `extraction_reason` 이 원문 범위 내
- [ ] `is_must_know=true` 기사들 `relevance_score` ≥ 8.0
- [ ] `trend_hashtags` 3~8 개
- [ ] issue_number 가 prepare-run / state.json / analyzed.json 에서 일치
- [ ] publish workflow 성공 시 `docs/index.html` commit 확인
- [ ] 카카오톡 메시지가 `📰 데일리 뉴스 · ...` (성공) 또는 `⚠️ 뉴스 생성 실패` (실패) 로 시작
