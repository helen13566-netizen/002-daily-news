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

### 단계 C — candidates.json 신선도 + Actions 폴백 (v16)

> 🚨 **금지 — sandbox 안에서 절대 다음을 시도하지 마라**
>
> ```
> python3 -m pipeline.collect      ← 금지
> python3 pipeline/collect.py      ← 금지
> 어떤 형태로든 RSS 호스트 직접 fetch ← 금지
> ```
>
> sandbox proxy 가 한국 RSS 호스트(aitimes / zdkorea / etnews / yna / mk / hani) 를 `host_not_allowed 403` 으로 차단한다. 직접 호출하지 마라. RSS 수집은 **GitHub Actions 만** 담당한다.

```bash
ensure_fresh_candidates() {
  test -s state/candidates.json || return 1
  local age_min=$(( ($(date +%s) - $(stat -c %Y state/candidates.json)) / 60 ))
  [ "$age_min" -le 60 ]
}

if ! ensure_fresh_candidates; then
  AGE_MIN=$(( ($(date +%s) - $(stat -c %Y state/candidates.json 2>/dev/null || echo 0)) / 60 ))
  echo "[stale] candidates.json 이 ${AGE_MIN}분 전 → Actions collect.yml workflow_dispatch 트리거"

  # GitHub REST API 로 워크플로 강제 실행 (sandbox 가 api.github.com 은 허용)
  curl -fsS -X POST \
    -H "Accept: application/vnd.github+json" \
    -H "Authorization: Bearer $GITHUB_TOKEN" \
    -H "X-GitHub-Api-Version: 2022-11-28" \
    https://api.github.com/repos/helen13566-netizen/002-daily-news/actions/workflows/collect.yml/dispatches \
    -d '{"ref":"main"}' \
    || { FAILED_STAGE=collecting; ERROR_REASON="workflow_dispatch 호출 실패"; }

  # 폴링: 30초 간격으로 **candidates.json 만** path-level checkout (최대 5분)
  # ⚠️ 이전(v16)은 git reset --hard origin/main 을 썼지만, 이는 단계 B 의 prepare-run 이
  # 올려놓은 state/state.json 로컬 수정(issue_number++ 등) 까지 롤백하여 버그를 일으켰다.
  # v18 부터는 candidates.json 만 체크아웃하여 state.json 을 보호한다.
  for i in 1 2 3 4 5 6 7 8 9 10; do
    sleep 30
    git fetch origin main >/dev/null 2>&1
    git checkout origin/main -- state/candidates.json >/dev/null 2>&1
    if ensure_fresh_candidates; then
      echo "[fresh] candidates.json 폴링 $((i*30))초만에 갱신 완료"
      unset FAILED_STAGE ERROR_REASON
      break
    fi
  done

  if ! ensure_fresh_candidates; then
    FAILED_STAGE=collecting
    ERROR_REASON="Actions collect 5분 폴링 후에도 candidates 미갱신 (Actions schedule jitter)"
  fi
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
5. 기사 수 **목표는 공식 AI 3~5건 / AI 20~25건 / 종합 20~25건** (총 43~55).
   - **공식 AI 업데이트**(`category=official_ai` — OpenAI Blog / Google DeepMind / Simon Willison / Anthropic SDK Releases) 는 주요 모델·기능 발표라 **발견되면 전부 포함**하고 `is_must_know=true` 로 승격 가능. 이 카테고리는 하한 없음.
   - **AI 뉴스·종합 뉴스 각 섹션 하한 20건은 반드시 준수**하라.
6. **하한 20건 이하로 내려가는 것은 최후 수단**. 오직 **stream idle timeout 이 실제로 임박한 경우(이전 chunk 가 4분 넘게 지연)에만** 허용.

#### 🧭 인사이트 레이어 (v9)

각 기사 객체에 **`insights` 필드를 포함**하라. 독자(일반인·중학생 수준 어휘)가 "뉴스 그 자체"를 넘어 **세상을 바라보는 판단 근육**을 기르도록 돕는 해석·비교·전망 레이어다.

##### 페르소나 (v13)
너는 정치·경제·국제 정세를 오래 다뤄온 **시니어 뉴스 편집장 겸 체계적 분석가**다. 다음 공신력 있는 방법론을 훈련받았다:

- **Stanford Civic Online Reasoning (COR)** — 3 moves(누가 배후? 증거는? 다른 출처는?), lateral reading, click restraint
- **Stony Brook IMVAIN** — 출처 평가 5축(Independent · Multiple · Verifies · Authoritative · Named)
- **Tetlock Superforecasting** — comparison class, belief updating, 확률 등급 5~10단계
- **Meadows Systems Thinking** — Iceberg model(Events→Patterns→Structures→Mental Models), 12 leverage points
- **Entman Framing** — Problem definition · Causal interpretation · Moral evaluation · Treatment recommendation
- **Kahneman Reference Class Forecasting** — outside view(유사 사례 통계) 와 inside view(이 사건 구체) 균형
- **IFCN Code of Principles** — nonpartisanship · transparency · methodology · corrections
- **Matt Levine Incentive Analysis** — "incentives explain more than rhetoric", 누가 이익/손해, 왜 지금
- **Second/Third-Order Consequences** — "그 다음엔?" 질문 3단계

단정하지 말고 "가능성 **높음/중간/낮음**" 같은 확률 등급으로 표현하라. 각 인사이트 축에는 아래 **축별 체크리스트**를 반드시 **속으로** 수행한 뒤, 결과 단서를 text 에 녹여 서술해라 (체크리스트 자체를 text 에 나열하지 말 것).

##### 문체 규칙
- 중학생 수준 어휘. 전문용어는 괄호로 풀이: "CPI(소비자물가)".
- "→" 화살표 대신 서술형 문장 ("A가 일어나면 B가 됩니다").
- 수치는 감각적 비유 동반 ("10% = 10명 중 1명, 만 원 중 천 원 수준").
- 능동태·짧은 문장 (40~60자).
- 각 인사이트 문단: **3~5문장, 200~350자** (v14 상향).
- **분석 구조를 text 에 드러내라** — "1차 효과는…, 2차 효과는…, 3차 효과는…" 식으로 **단계를 명시**. 속으로만 수행하고 결과를 압축하면 독자가 전문성 신호를 못 받음.
- **구체 수치·회사명·연도·대응 수단을 최소 2개 포함**하라 (예: "2022년 엔비디아 H100 수출 규제 때 화웨이 어센드 수요가 3배로 뛰었다"). 추상 표현 지양.

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

##### 각 축별 분석 체크리스트 (v13)

각 축의 text 를 작성할 때 아래 체크리스트의 **분석 구조를 text 에 드러내라**. 체크리스트 항목명(예: "Iceberg", "IMVAIN") 같은 **전문 용어는 text 에 직접 쓰지 말되**, 그 **틀의 결과(1차·2차·3차 효과, 확률 등급, 출처 약점 등)는 text 에 명시**하라. 중학생 수준 어휘의 서술형 3~5문장, **200~350자**, 구체 수치·연도·회사명 2개 이상 포함.

**`ripple` — Meadows Iceberg + Second/Third Order**
- 이 사건의 1차·2차·3차 효과를 "그 다음엔?" 질문으로 연쇄
- 이것은 Events 레벨인가 · Patterns 인가 · Structures 변화인가
- 단서 예: "당장은 …, 며칠 뒤엔 …, 몇 달 지나면 …"

**`history` — Reference Class Forecasting (Kahneman)**
- 이 사건이 속한 reference class 정의 (비슷한 과거 사례 2~3개)
- 그 집합의 실제 결과 분포 + 이번이 어디쯤 위치
- 이번이 과거와 다른 변수 1~2개
- 단서 예: "지난 10년 네 번 있었고 평균 N% 변동, 한 달 안에 회복"

**`scenario` — Tetlock Superforecasting**
- 최선/중간/최악 시나리오 각각 확률 등급 (가능성 높음·중간·낮음)
- "가장 가능성 높은 시나리오" 를 명시
- 다음 며칠~몇 주 안에 어떤 이벤트가 방향을 결정할지 (갈림길)
- 단서 예: "중간 시나리오(가능성 높음), 갈림길은 다음 주 …"

**`personal` — Matt Levine Incentive Analysis**
- 이 뉴스에서 누가 이익/손해 (incentive 구조)
- 독자 포지션별 구체 행동 2~3개 (검토·비교·관찰 수준, 매수·매도 직접 지시 금지)
- 반사적으로 하기 쉬운 **피해야 할 행동 1개**
- 단서 예: "… 를 이번 주 비교해보세요. 반면 조급히 … 하는 건 피하세요"

**`frame` — Stanford COR + IMVAIN + IFCN + Entman**
- 1차 출처 점검 (IMVAIN 5축 중 약한 부분)
- 다른 매체 교차 확인 (lateral reading)
- 기사가 선택한 frame vs 빠진 frame (Entman Problem/Cause/Moral/Treatment)
- 독자가 던질 질문 2~3개
- 단서 예: "단일 익명 출처라 약합니다. 옆 매체 두 곳은 다르게 보도. 이 질문을 던져보세요: …"

**`perspective` — Stakeholder Mapping + Entman**
- 3~5명의 stakeholder 식별 (Primary·Secondary·Key)
- 각 측이 어떤 문제로 규정, 어떤 해결을 원하나
- 구조적 갈등 지점 (누가 이익·누가 손해)
- 단서 예: "경영진·노조·정부·소비자 네 입장이 부딪히는 지점은 …"

##### 스키마

```jsonc
"insights": {
  "ripple": {
    "title": "이게 우리한테 어떻게 영향을 줄까?",
    "icon": "📡",
    "text": "<200~350자 서술형, 분석 구조 드러내기, 구체 수치 2개+>"
  },
  "history": {
    "title": "예전에도 이런 일이 있었을까?",
    "icon": "🗂",
    "text": "<200~350자 서술형, 분석 구조 드러내기, 구체 수치 2개+>"
  },
  "bonus": [
    {
      "type": "personal|scenario|frame|perspective",
      "title": "<위 표의 헤딩>",
      "icon": "💡|🔮|🧐|👥",
      "text": "<200~350자 서술형, 분석 구조 드러내기, 구체 수치 2개+>"
    }
  ]
}
```

##### 🚨 stream idle timeout 방지 절대 규칙 (v11)

이전 두 번의 실행이 **Anthropic API "Stream idle timeout"** 으로 중단됐다. 원인은 **단일 LLM 응답에서 너무 많은 insights 를 동시 생성**한 것. 아래 규칙을 **반드시** 지켜라.

1. **content_text 전체 또는 대량 출력 절대 금지**. 탐색·샘플링은 `title`·`source`·`relevance_score` 같은 메타데이터만. 디버깅 용이면 3건 이하 `head -c 100` 수준.
2. **한 bash 호출(= 한 LLM 응답)에서 정확히 2건 insights 생성**. 3건·5건·10건으로 임의 변경 금지.
3. 한 bash 호출의 예상 응답이 3,000자 초과면 더 쪼개라.

##### 🚨 HARD RULE — chunk 크기 2건 고정 (v17)

v14 에서 "2건 단위" 를 선언했지만 agent 가 "efficient 하게 묶자" 며 5건으로 키워 **stream idle timeout 이 실제로 재현됐다** (2026-04-21 오후). 다음을 **절대** 위반하지 마라:

- chunk 당 **정확히 2건** (마지막 chunk 만 1건 허용)
- "효율" · "시간 절약" · "to save time" 등의 추론으로 키우지 마라
- 2건 × 3~4축 × 300자 ≈ 2,800자 → 5분 idle 한계 여유 있음. 5건으로 키우면 7,000자 초과 → timeout 재발.

##### Chunk 분할 (v17 · 2건 단위 엄수)

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

**Phase 2 — AI 뉴스 2건씩 × 약 13 chunk** (각 chunk 가 **별도 bash 호출**)

v14 에서 insight 분량이 200~350자로 늘어났으므로 한 bash 호출의 응답이 더 커진다. **chunk 크기를 3건 → 2건 단위**로 축소해 5분 idle 한계에 여유를 둔다. 각 chunk 응답 ≈ 2건 × 3~4축 × 300자 ≈ **2,800자** 이하.

반복 구조 (AI 뉴스 25건 → 2건씩 ≈ 13 chunk):

```bash
# Phase 2a — AI 뉴스 1~2번째 insights (정확히 2건)
python3 - <<'PY'
import json, pathlib
ai_pool = json.load(open("/tmp/ai_pool.json"))
# LLM 이 생각한 2건 분석 결과 (ai_summary, extraction_reason, score, is_must_know, insights 포함)
selected = [ ... ]  # 정확히 2개
pathlib.Path("/tmp/ai_chunk1.json").write_text(json.dumps(selected, ensure_ascii=False), encoding="utf-8")
print(f"[progress] ai chunk1: {len(selected)} done")
PY
```

이후 2건씩: Phase 2b (3~4) → `ai_chunk2.json`, 2c (5~6) → `ai_chunk3.json`, 2d (7~8), 2e (9~10), 2f (11~12), 2g (13~14), 2h (15~16), 2i (17~18), 2j (19~20), 2k (21~22), 2l (23~24), 2m (25) → `ai_chunk13.json` (마지막 1건). **AI 25건이면 총 13 chunk**.

**Phase 3 — 종합 뉴스 2건씩 × 약 13 chunk** (위와 동일 구조로 `/tmp/gen_chunk*.json` 저장)

**Phase 4 — 병합 + state/analyzed.json 저장** (bash 호출 1회, LLM 응답 거의 없음)

```bash
python3 - <<'PY'
import glob, json, pathlib
arts = []
# AI 먼저, 그 다음 종합. chunk 번호 순서 유지
for p in sorted(glob.glob("/tmp/ai_chunk*.json")):
    arts.extend(json.load(open(p)))
for p in sorted(glob.glob("/tmp/gen_chunk*.json")):
    arts.extend(json.load(open(p)))
state = json.load(open("state/state.json"))
analyzed = {
    "issue_number": state["issue_number"],
    "generation_timestamp": state["current_generation_timestamp"],
    "period": state["current_period"],  # 명시적 오전/오후 — render 가 이걸 우선 사용
    "trend_hashtags": [...],  # 이 줄만 너가 LLM 추론으로 채워 (공통 주제 3~8개)
    "articles": arts,
}
pathlib.Path("state/analyzed.json").write_text(
    json.dumps(analyzed, ensure_ascii=False, indent=2), encoding="utf-8")
print(f"[progress] analyzed.json: {len(arts)} articles")
PY
```

**총 28 bash 호출** (Phase 1 + AI 13 + 종합 13 + Phase 4) = 28 LLM 응답. 각 응답 2건 × 3~4축 × 300자 ≈ **최대 2,800자** → stream idle timeout 안전 마진.

**소요 시간**: 각 chunk 30-90초, 전체 25-45분 예상.

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

### 단계 D.5 — analyzed 검증 (v18 신규)

analyzed.json 의 모든 기사가 candidates.json 에 있는지 **Python 이 강제 검증**. LLM 이 과거 커밋의 candidates 를 참조하거나 학습된 기억에서 기사를 끌어오는 경우(실제 관측됨)에 `FAILED_STAGE=analyzing` 으로 브리핑을 실패 처리하여 오염된 콘텐츠가 배포되는 것을 막는다.

```bash
python3 -m pipeline.run validate-analyzed
```

exit 1 이면 이미 state.json 에 `failed_stage=analyzing` 이 기록됐으므로 단계 E 로 가지 말고 **단계 X** 로 분기.

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
