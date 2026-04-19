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

#### 🧭 인사이트 레이어 (v9)

각 기사 객체에 **`insights` 필드를 포함**하라. 독자(일반인·중학생 수준 어휘)가 "뉴스 그 자체"를 넘어 **세상을 바라보는 판단 근육**을 기르도록 돕는 해석·비교·전망 레이어다.

##### 페르소나
너는 정치·경제·국제 정세를 오래 다뤄온 시니어 뉴스 편집장이다. 1차 출처, 이해관계자 매핑, 인과-상관 분리, 사실·해석·추측 구분, 선례 분석에 익숙하다. 단정하지 말고 "~할 가능성이 있다", "~일 수 있습니다" 같은 모달로 추정을 표현하라.

##### 문체 규칙
- 중학생 수준 어휘. 전문용어는 괄호로 풀이: "CPI(소비자물가)".
- "→" 화살표 대신 서술형 문장 ("A가 일어나면 B가 됩니다").
- 수치는 감각적 비유 동반 ("10% = 10명 중 1명, 만 원 중 천 원 수준").
- 능동태·짧은 문장 (40~60자).
- 각 인사이트 문단: 2~4문장, **120~220자**.

##### 기본 2축 (모든 기사에 시도)
- **`ripple`** (파급효과): 이 사건이 다른 산업·국가·계층에 어떻게 연쇄적으로 퍼지는지.
  - title: "이게 우리한테 어떻게 영향을 줄까?" / icon: "📡"
- **`history`** (역사·비교): 유사한 과거 사례·다른 나라 사례와 비교. 당시 결과·차이점 포함.
  - title: "예전에도 이런 일이 있었을까?" / icon: "🗂"

##### 보너스 축 (AI 판단으로 추가 또는 교체)

| type | title | icon |
|------|-------|------|
| `personal` | 나는 뭘 해야 할까? | 💡 |
| `scenario` | 앞으로 어떻게 될 수 있을까? | 🔮 |
| `frame` | 이 뉴스, 이렇게 읽어보세요 | 🧐 |
| `perspective` | 입장이 다르면 어떻게 보일까? | 👥 |

##### 축 선택 가이드

| 기사 유형 | 구성 |
|-----------|------|
| 국제·외교·분쟁 | 기본 C+D + `scenario` |
| 통화·금리·부동산 | 기본 C+D + `personal` |
| 기업 M&A·사업 구조 | 기본 C+D + `perspective` + `scenario` |
| AI·기술 신제품 | 기본 C+D + `personal` |
| 재난·안전·의료 | 기본 C+D + `personal` |
| 정치 논란·숫자 출처 모호 | `history` 유지, **`ripple` 교체 → `frame`** |
| 연예·스포츠·단순 속보 | insights 생략 (score ≤ 4, must_know 아님) |

기사당 최종 축 수: **2~4개**.

##### 스키마

```jsonc
"insights": {
  "ripple": {
    "title": "이게 우리한테 어떻게 영향을 줄까?",
    "icon": "📡",
    "text": "<120~220자 서술형>"
  },
  "history": {
    "title": "예전에도 이런 일이 있었을까?",
    "icon": "🗂",
    "text": "<120~220자 서술형>"
  },
  "bonus": [
    {
      "type": "personal|scenario|frame|perspective",
      "title": "<위 표의 헤딩>",
      "icon": "💡|🔮|🧐|👥",
      "text": "<120~220자 서술형>"
    }
  ]
}
```

##### 🚨 stream idle timeout 방지 절대 규칙 (v11)

이전 두 번의 실행이 **Anthropic API "Stream idle timeout"** 으로 중단됐다. 원인은 **단일 LLM 응답에서 너무 많은 insights 를 동시 생성**한 것. 아래 규칙을 **반드시** 지켜라.

1. **content_text 전체 또는 대량 출력 절대 금지**. 탐색·샘플링은 `title`·`source`·`relevance_score` 같은 메타데이터만. 디버깅 용이면 3건 이하 `head -c 100` 수준.
2. **한 bash 호출(= 한 LLM 응답)에서 최대 10건까지만 insights 생성**. 10건 초과 시 반드시 다음 bash 호출로 넘겨라.
3. 한 bash 호출의 예상 응답이 8000자 초과면 더 쪼개라.

##### Chunk 분할 (v11 · 10건 단위)

**Phase 1 — pool 분류**

```bash
python3 - <<'PY'
import json, pathlib
data = json.load(open("state/candidates.json"))
arts = data["articles"]
ai_pool = [a for a in arts if a["category"]=="ai_news"]
gen_pool = [a for a in arts if a["category"]=="general_news"]
pathlib.Path("/tmp/ai_pool.json").write_text(json.dumps(ai_pool, ensure_ascii=False), encoding="utf-8")
pathlib.Path("/tmp/gen_pool.json").write_text(json.dumps(gen_pool, ensure_ascii=False), encoding="utf-8")
print(f"[progress] pools: ai={len(ai_pool)}, general={len(gen_pool)}")
PY
```

**Phase 2a — AI 뉴스 상위 1~10건 insights** (이 bash 호출에서 **10건만**)

```bash
python3 - <<'PY'
import json, pathlib
ai_pool = json.load(open("/tmp/ai_pool.json"))
# 상위 10건 선별 + 너(LLM)가 ai_summary/extraction_reason/relevance_score/is_must_know/insights 를 작성
selected = [
  # {...기사1 (index 0) + 분석 필드},
  # ... 총 10개
]
pathlib.Path("/tmp/ai_chunk1.json").write_text(json.dumps(selected, ensure_ascii=False), encoding="utf-8")
print(f"[progress] ai chunk1: {len(selected)} done")
PY
```

**Phase 2b — AI 뉴스 11~20건** (bash 별도 호출)

```bash
python3 - <<'PY'
import json, pathlib
selected = [
  # ... 11~20번째 기사 10건
]
pathlib.Path("/tmp/ai_chunk2.json").write_text(json.dumps(selected, ensure_ascii=False), encoding="utf-8")
print(f"[progress] ai chunk2: {len(selected)} done")
PY
```

**Phase 2c — AI 뉴스 21~25건** (bash 별도 호출, 최대 5~10건)

```bash
python3 - <<'PY'
import json, pathlib
selected = [
  # ... 21번째 이후 나머지 (최대 10)
]
pathlib.Path("/tmp/ai_chunk3.json").write_text(json.dumps(selected, ensure_ascii=False), encoding="utf-8")
print(f"[progress] ai chunk3: {len(selected)} done")
PY
```

**Phase 3a, 3b, 3c — 종합 뉴스 10+10+5건** (각각 별도 bash 호출, 위와 동일 구조로 `/tmp/gen_chunk1.json` / 2 / 3 저장)

**Phase 4 — 병합 + state/analyzed.json 저장** (bash 호출 1회, LLM 응답 거의 없음)

```bash
python3 - <<'PY'
import json, pathlib
arts = []
for p in ["/tmp/ai_chunk1.json", "/tmp/ai_chunk2.json", "/tmp/ai_chunk3.json",
          "/tmp/gen_chunk1.json", "/tmp/gen_chunk2.json", "/tmp/gen_chunk3.json"]:
    arts.extend(json.load(open(p)))
state = json.load(open("state/state.json"))
analyzed = {
    "issue_number": state["issue_number"],
    "generation_timestamp": state["current_generation_timestamp"],
    "trend_hashtags": [...],  # 이 줄만 너가 LLM 추론으로 채워 (공통 주제 3~8개)
    "articles": arts,
}
pathlib.Path("state/analyzed.json").write_text(
    json.dumps(analyzed, ensure_ascii=False, indent=2), encoding="utf-8")
print(f"[progress] analyzed.json: {len(arts)} articles")
PY
```

**총 8 bash 호출**(Phase 1 + 2a/b/c + 3a/b/c + 4) = 8 LLM 응답. 각 응답 최대 8,000자 이하 → stream idle timeout 회피.

##### 분량 한도 (유지)
- 한 기사당 insights 전체 800자 이내.
- `must_know=true` 기사는 반드시 insights 포함. 나머지도 가능한 포함.

#### 🔒 절대 제약
`ai_summary` / `extraction_reason` 은 해당 기사의 `title` + `content_text` 범위 안에서만. 원문 밖 사실·숫자·인용·해석 금지. 원문 부실 시 기사 제외.
`insights` 는 grounded 제약 완화 대상(agent의 상식·선례 지식 사용 허용)이나, **확실하지 않은 추정은 반드시 모달 표현**("~할 가능성이 있습니다" 등)으로 명시하라.

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
