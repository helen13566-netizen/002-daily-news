# Remote Agent 실행 절차서 (v6 · PAT + Contents API)

## v6 핵심

sandbox 환경 실측:
- `git push` (SSH 22/443) — proxy 가 차단 (400)
- `git push` (HTTPS) — 자격증명 없으면 불가
- MCP `push_files`/`create_or_update_file` — 권한 403
- **`GITHUB_TOKEN` 주입 → `requests` 로 Contents API PUT** — 작동 ✅

trigger prompt 첫머리에서 `GITHUB_TOKEN` 이 export 된다. agent 는 `scripts/upload_files.py` 로 원격 파일을 업로드한다.

## 환경 가정

- working directory: clone 된 repo
- `GITHUB_TOKEN` 환경변수 set (repo scope)
- `git remote get-url origin` 은 https URL
- `TZ=Asia/Seoul`

## 보안 수칙

- **절대 `$GITHUB_TOKEN` 값을 `echo`, `cat`, 로그에 출력하지 마라**
- `env` 출력, `set -x` 금지 (셸 trace 남김)
- upload_files.py 는 내부적으로만 토큰을 사용하고 stdout/stderr 에는 HTTP 상태만 기록

## 파이프라인

```
Actions collect.yml (cron 06:55/17:55 KST)
  → RSS 6개 수집 → state/candidates.json 커밋
         ↓
Remote agent (cron 07:00/18:00 KST)
  → git pull (candidates.json 수신)
  → prepare-run (state.json 로컬 수정, issue_number 증가)
  → grounded 분석 → state/analyzed.json
  → render → docs/index.html + archive/YYYY-MM-DD-HHMM.html
  → mark-success → state/state.json 갱신
  → scripts/upload_files.py 로 4개 파일을 Contents API 로 업로드
  → 카카오 MCP 성공 메시지
```

## 단계별

### 단계 A — git pull

```bash
git pull --ff-only origin main || {
  git fetch origin main && git reset --hard origin/main
}
```

### 단계 B — prepare-run

```bash
PREP=$(python3 -m pipeline.run prepare-run --period "$PERIOD")
echo "$PREP"
ISSUE_NUMBER=$(echo "$PREP" | python3 -c "import sys,json; print(json.load(sys.stdin)['issue_number'])")
```

### 단계 C — candidates.json 신선도

```bash
test -s state/candidates.json || { FAILED_STAGE=collecting; ERROR_REASON="candidates.json 없음"; }
AGE_MIN=$(( ($(date +%s) - $(stat -c %Y state/candidates.json)) / 60 ))
if [ "$AGE_MIN" -gt 60 ]; then
  FAILED_STAGE=collecting
  ERROR_REASON="candidates.json 이 ${AGE_MIN}분 전 수집 (Actions cron 누락 의심)"
fi
```

`FAILED_STAGE` set 되면 **단계 X**.

### 단계 D — grounded 분석

`state/candidates.json` → `state/analyzed.json`.

#### ⚡ 효율 수칙 (시간 예산 엄수, v8)

sandbox 세션에는 시간 한계가 있다. 다음 규칙을 엄수하지 않으면 타임아웃으로 실패 처리된다.

1. **candidates.json 은 단 한 번만 로드하라.** Python 스크립트를 여러 번 실행해 탐색·샘플링·통계 출력하지 마라.
2. **탐색을 위해 기사의 `content_text` 전체를 출력하지 마라.** stdout 에 찍히는 모든 토큰은 세션 시간을 먹는다. 확인용이면 title/source/score 등 요약 메타만 3건 이하로.
3. **단일 Python 블록으로 분석을 끝내라.** 권장 파이프라인:
   ```
   import json, pathlib
   data = json.load(open("state/candidates.json"))
   articles = data["articles"]
   # 1) 카테고리별 분류 (이미 category 필드 있음 — 그대로 사용)
   ai_pool = [a for a in articles if a["category"]=="ai_news"]
   gen_pool = [a for a in articles if a["category"]=="general_news"]
   # 2) 1차 스코어링은 title + keywords + source 만으로 (빠른 heuristic)
   # 3) 상위 N건 선별 (AI 20, 종합 20)
   # 4) 선별된 기사만 content_text 를 읽어 ai_summary/extraction_reason/relevance_score 를 당신 추론으로 채움
   # 5) analyzed = {"issue_number": ..., "generation_timestamp": ..., "trend_hashtags": [...], "articles": [...]}
   # 6) pathlib.Path("state/analyzed.json").write_text(json.dumps(analyzed, ensure_ascii=False, indent=2), encoding="utf-8")
   ```
4. **선별 후보 리스트는 내부 변수로만.** stdout 에 인덱스 리스트나 제목 리스트 나열하지 마라.
5. 기사 수가 목표치(AI 20 / 종합 20)에 미달해도 OK — **억지로 채우지 말고 바로 진행**.
6. 시간이 촉박하면 각 섹션 **하한 10건**까지 완화해도 좋다 (총 20건). 품질 > 분량.

#### 🔒 절대 제약
`ai_summary` / `extraction_reason` 은 해당 기사의 `title` + `content_text` 범위 안에서만. 원문 밖 사실·숫자·인용·해석 금지. 원문 부실 시 기사 제외.

#### 출력 schema
```json
{
  "issue_number": <prepare-run 의 issue_number>,
  "generation_timestamp": <prepare-run 의 generation_timestamp>,
  "trend_hashtags": ["...", ...],
  "articles": [
    {"article_id": "...", "title": "...", "source": "...",
     "published_at": "...", "original_url": "...",
     "content_text": "...", "category": "ai_news|general_news",
     "keywords": [...],
     "ai_summary": "<140~220자>",
     "extraction_reason": "<40~80자>",
     "relevance_score": <0-10>,
     "is_must_know": <score >= 8.0>}
  ]
}
```

#### 점수 — 5차원 최고값
1. 경제/생계  2. 안전/건강  3. 정책/법제  4. 기술/일자리  5. 국제정세

루머/가십/연예/스포츠 ≤ 4점.

#### 분량 목표 (v7 상향 조정)

- **AI 뉴스(`category=="ai_news"`) 최소 20건, 상한 25건**
- **종합 뉴스(`category=="general_news"`) 최소 20건, 상한 25건**
- 총 40~50건이 되도록 선별
- candidates 에 해당 카테고리 기사가 목표치 미달이면 가능한 전부 포함 (억지로 채우지 말 것, 루머·가십·연예·스포츠로 쿼터 채우지 말 것)
- **각 카테고리 모두 3건 미달 시** `FAILED_STAGE=analyzing`
- 각 섹션 내에서 `relevance_score` 내림차순 정렬 (render 가 자동 처리)

#### 저장
```bash
python3 - <<'PY'
import json, pathlib
analyzed = { ... }
pathlib.Path("state/analyzed.json").write_text(
    json.dumps(analyzed, ensure_ascii=False, indent=2), encoding="utf-8")
PY
python3 -m pipeline.run mark-stage --stage analyzing
```

### 단계 E — render (로컬)

```bash
python3 -m pipeline.run render
python3 -m pipeline.run mark-success
ls -la docs/index.html archive/ state/
```

### 단계 F — Contents API 로 업로드

```bash
# archive 의 이번 파일명 추출
ARCHIVE_FILE=$(ls -t archive/*.html 2>/dev/null | head -1)

python3 scripts/upload_files.py \
  "news: ISSUE #${ISSUE_NUMBER} ${PERIOD} 브리핑 $(date +%Y-%m-%d_%H:%M_KST)" \
  docs/index.html \
  "$ARCHIVE_FILE" \
  state/state.json \
  state/analyzed.json
```

stderr 에 HTTP 상태만 로깅됨 (토큰 값 비출력). 실패 시 3회 자동 재시도 후 예외.

실패 시 `FAILED_STAGE=deploying` → 단계 X.

### 단계 G — 카카오 성공 알림

```bash
python3 -m pipeline.run mark-stage --stage notifying
SUCCESS_MSG=$(python3 -m pipeline.run notify-success)
echo "=== 전송 메시지 ==="
echo "$SUCCESS_MSG"
```

**PlayMCP 호출**:
```
도구: mcp__claude_ai_PlayMCP__KakaotalkChat-MemoChat
인자: text=<SUCCESS_MSG 전체>, 수정·요약 금지
```

**MCP 응답 원문을 stdout 에 출력**.

MCP 실패 3회 재시도. 파이프라인은 이미 성공이므로 MCP 실패해도 completed.

### 단계 H — 종료 JSON

```json
{"status": "completed", "issue_number": N, "article_count": N, "failed_stage": null, "kakao_message": "<원문>", "mcp_kakao_response": "<원문>", "duration_seconds": N}
```

---

## 단계 X — 실패 처리

```bash
python3 -m pipeline.run mark-failure --stage "$FAILED_STAGE" --reason "$ERROR_REASON"

# state.json 만 업로드 (docs 보존)
python3 scripts/upload_files.py \
  "state: failure at $FAILED_STAGE (ISSUE #$ISSUE_NUMBER $PERIOD)" \
  state/state.json || echo "[state upload 실패 — 계속 진행]" >&2

FAILURE_MSG=$(python3 -m pipeline.run notify-failure)
echo "$FAILURE_MSG"
```

PlayMCP 로 `FAILURE_MSG` 전송 (3회 재시도). stdout JSON:
```json
{"status": "failed", "failed_stage": "...", "error_reason": "...", "kakao_message": "<원문>", "mcp_kakao_response": "<원문>"}
```

종료 코드 0.

## 체크리스트

- [ ] `GITHUB_TOKEN` set 확인 (`[ -n "$GITHUB_TOKEN" ]`)
- [ ] candidates.json 60분 이내
- [ ] analyzed grounded 준수
- [ ] must_know score ≥ 8.0
- [ ] issue_number 일치
- [ ] upload_files.py 200/201 응답
- [ ] 토큰 값이 stdout/stderr 에 출력되지 않았는지 (`env`, `set -x` 금지)
- [ ] 카카오 MCP 응답 원문 stdout 기록
