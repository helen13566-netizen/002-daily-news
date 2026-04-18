# Remote Agent 실행 절차서

이 문서는 매일 07:00 KST(오전) · 18:00 KST(오후)에 `/schedule` 원격 트리거로 발화되는 Claude Opus 4.7 에이전트가 수행해야 할 절차를 정의한다. Task 8에서 이 문서의 내용이 cron trigger prompt에 삽입된다.

## 0. 역할과 목표

당신(에이전트)은 **데일리 뉴스 브리핑 파이프라인**의 실행자다. RSS 수집·필터링·HTML 렌더링·git 배포는 Python 스크립트(`pipeline.run` CLI)가 담당하고, 당신은:

1. 파이프라인 단계별 CLI 호출을 bash로 직접 실행
2. `state/candidates.json`을 읽어 **grounded 분석**(기사별 요약·추출이유·스코어링·트렌드 해시태그)을 수행하고 `state/analyzed.json`을 작성
3. 실패 시 **최대 3회 재시도**, 모두 실패하면 이전 `docs/index.html`을 그대로 두고 카카오톡 실패 알림 전송
4. 성공 시 `docs/index.html` + `state/state.json` 등을 커밋·푸시하고 카카오톡 성공 알림 전송

## 1. 사전 조건

- 워킹 디렉토리: `/home/helen/Dev/002-데일리뉴스` (있으면 이동, 없으면 `git clone https://github.com/helen13566-netizen/002-daily-news.git` 로 획득)
- git 원격: `origin = https://github.com/helen13566-netizen/002-daily-news.git` (main 브랜치)
- 커밋 신원: `git -c user.email=helen1356@naver.com -c user.name=helen13566-netizen commit ...`
- Python 의존성: `pip install --user --break-system-packages -r requirements.txt` (이미 설치되어 있다면 스킵)
- 카카오톡: PlayMCP `mcp__claude_ai_PlayMCP__KakaotalkChat-MemoChat` 사용 가능
- 시각: `TZ=Asia/Seoul`, 모든 타임스탬프는 KST ISO-8601

## 2. 파이프라인 단계

### 단계 A — 환경 준비

```bash
cd /home/helen/Dev/002-데일리뉴스 || git clone https://github.com/helen13566-netizen/002-daily-news.git /tmp/daily-news && cd /tmp/daily-news
git pull --rebase origin main
```

### 단계 B — `prepare-run` (issue_number 증가·retry 초기화)

트리거 이름에 따라 `PERIOD` 결정:
- 07:00 KST 트리거 → `PERIOD=오전`
- 18:00 KST 트리거 → `PERIOD=오후`

```bash
python3 -m pipeline.run prepare-run --period "$PERIOD"
```

stdout JSON에서 `issue_number`, `generation_timestamp`를 기억한다.

### 단계 C — `collect` (RSS 수집)

최대 3회 재시도:

```bash
for attempt in 1 2 3; do
  if python3 -m pipeline.run collect; then
    break
  fi
  if [ "$attempt" = "3" ]; then
    RETRY_EXHAUSTED=1
    FAILED_STAGE=collecting
    break
  fi
  sleep $((attempt * 5))
done
```

실패 지속 시 → **단계 X (실패 처리)** 로 분기.

### 단계 D — grounded 분석 (당신이 직접 수행)

`state/candidates.json`을 읽어 기사별로 아래 5개 필드를 추가해 `state/analyzed.json`으로 저장한다.

#### 입력 형태 (candidates.json)

```json
{
  "collection_timestamp": "2026-04-19T07:01:05+09:00",
  "source_stats": {...},
  "articles": [
    {"article_id": "...", "title": "...", "source": "AI타임스",
     "published_at": "2026-04-19T06:48:00+09:00",
     "original_url": "https://...",
     "content_text": "...",
     "category": "ai_news" | "general_news",
     "keywords": ["GPT", ...]}
  ]
}
```

#### 출력 형태 (analyzed.json)

```json
{
  "issue_number": <state.issue_number>,
  "generation_timestamp": <state.current_generation_timestamp>,
  "trend_hashtags": ["생성형AI", "반도체", "금리", ...],
  "articles": [
    {
      "article_id": "...", "title": "...", "source": "...",
      "published_at": "...", "original_url": "...",
      "content_text": "...", "category": "...",
      "keywords": [...],
      "ai_summary": "...",              <- 당신이 생성
      "extraction_reason": "...",        <- 당신이 생성
      "relevance_score": 8.5,            <- 당신이 생성 (0-10)
      "is_must_know": true               <- score ≥ 8.0
    }
  ]
}
```

#### 🔒 **grounded 생성 절대 제약**

- **`ai_summary`와 `extraction_reason`은 해당 기사의 `title` + `content_text` 범위 안에서만 생성한다. 원문에 없는 사실·숫자·인용을 추가하지 마라. 환각 금지.**
- 원문 정보가 부족해 요약을 만들 수 없는 기사는 해당 기사를 analyzed.json에서 제외한다 (억지로 채우지 말 것).
- `relevance_score`는 기사 내용 기반의 판단이지만, 스코어 자체는 "원문 범위 초과"가 아니다 — 아래 5가지 상황에 대한 당신의 독립 판단.

#### 점수 산정 기준 — 인생중요뉴스 5가지 상황 (0-10)

각 차원을 0~10으로 속으로 평가한 뒤 **최고값**을 `relevance_score`로 한다. 8.0 이상이면 `is_must_know=true`.

1. **경제/생계** — 금리·물가·부동산·고용·환율 등 독자 지갑에 직접 영향
2. **안전/건강** — 재난·사고·질병·공공안전·의료
3. **정책/법제** — 법안·규제·세제·공공정책 변동
4. **기술/일자리** — AI·자동화로 인한 직업·업무 방식 변화, 주요 IT 산업 전환
5. **국제정세** — 전쟁·외교·글로벌 공급망·반도체 수출 규제 등 한국에 파급되는 국제 이슈

단순 루머·가십·연예·스포츠 결과는 최대 4점 이내. AI 기술 소개 기사는 실제 산업·일자리 파급이 있어야 7점 이상.

#### `ai_summary`

- 한국어 2~3문장, 140~220자
- 원문에 있는 숫자·고유명사는 그대로 사용
- 기사의 **결론**을 먼저, **근거**를 이후에 배치
- 원문이 단순 속보(1~2문장)면 요약도 1문장으로 짧게

#### `extraction_reason`

- 한국어 1문장, 40~80자
- "왜 오늘 이 기사를 꼭 봐야 하는가"를 독자 관점에서
- 예: "금리 인상이 주담대 이자에 즉시 반영되어 가계 부담이 증가합니다."

#### `trend_hashtags` (최상위 메타데이터)

- 오늘 전체 analyzed 기사에서 반복 등장한 주제·키워드를 해시태그 3~8개로 압축
- 한글 위주, `#` 접두사 없이 문자열 리스트
- 예: `["생성형AI", "한미FTA", "반도체수출규제", "금리동결"]`

#### 기사 최소/최대 수

- 최소 3개 기사가 analyzed에 있어야 의미 있는 브리핑 — 3개 미만이면 `mark-failure --stage analyzing --reason "kept articles < 3"` 후 재시도
- 최대 30개까지 포함 (너무 많으면 `relevance_score` 상위 30개만 유지)
- 섹션 균형: ai_news ≥ 2개, general_news ≥ 2개 권장 (못 맞추면 무시하고 진행)

#### analyzed.json 저장

당신은 Python으로 파일을 직접 쓸 수 있다:

```bash
python3 - <<'PY'
import json, pathlib
analyzed = { ... 당신이 구성한 dict ... }
pathlib.Path("state/analyzed.json").write_text(json.dumps(analyzed, ensure_ascii=False, indent=2), encoding="utf-8")
PY
```

저장 후 `mark-stage`:

```bash
python3 -m pipeline.run mark-stage --stage analyzing
```

### 단계 E — `render` (HTML 생성)

```bash
for attempt in 1 2 3; do
  if python3 -m pipeline.run render; then
    break
  fi
  [ "$attempt" = "3" ] && RETRY_EXHAUSTED=1 && FAILED_STAGE=generating && break
  sleep $((attempt * 3))
done
```

### 단계 F — 커밋 & 푸시 (배포)

```bash
python3 -m pipeline.run mark-stage --stage deploying

git add docs/ state/ archive/
git -c user.email=helen1356@naver.com -c user.name=helen13566-netizen commit -m "news: ISSUE #${ISSUE_NUMBER} ${PERIOD} 브리핑 $(date +%Y-%m-%d_%H:%M)"

for attempt in 1 2 3; do
  if git push origin main; then break; fi
  [ "$attempt" = "3" ] && RETRY_EXHAUSTED=1 && FAILED_STAGE=deploying && break
  sleep $((attempt * 5))
done
```

실패 지속 시 → 단계 X. 성공 시 `python3 -m pipeline.run mark-success`.

### 단계 G — 카카오톡 성공 알림

```bash
python3 -m pipeline.run mark-stage --stage notifying
MESSAGE=$(python3 -m pipeline.run notify-success)
```

카카오 MCP 호출:

```
mcp__claude_ai_PlayMCP__KakaotalkChat-MemoChat
  text: <MESSAGE 전체 내용>
```

MCP 호출 실패 시 3회 재시도 (간격 5초). 최종 실패해도 HTML은 이미 배포된 상태이므로 `mark-success`는 유지하고 stderr에 경고만 남긴다.

### 단계 H — 완료

```bash
python3 -m pipeline.run mark-success  # 이미 호출되었다면 재호출해도 무해 (retry 0, completed)

git add state/
git -c user.email=helen1356@naver.com -c user.name=helen13566-netizen commit -m "state: ISSUE #${ISSUE_NUMBER} completed" && git push || true
```

## 3. 단계 X — 실패 처리

어느 단계에서든 `RETRY_EXHAUSTED=1`이 되면:

```bash
python3 -m pipeline.run mark-failure --stage "$FAILED_STAGE" --reason "$ERROR_REASON"
git add state/
git -c user.email=helen1356@naver.com -c user.name=helen13566-netizen commit -m "state: failure at ${FAILED_STAGE}" && git push || true

FAILURE_MESSAGE=$(python3 -m pipeline.run notify-failure)
```

카카오 MCP로 `FAILURE_MESSAGE` 전송. 그리고 **HTML은 건드리지 않는다** — docs/index.html은 이전 성공본 그대로 유지된다(render 실패 시에는 애초에 생성 안 됨, collect/analyzing/deploying 실패 시에도 docs/는 건드리지 않음).

종료 코드는 0으로 반환 (trigger 재발화 막기 위해).

## 4. 체크리스트 (에이전트 자기 검증)

브리핑 종료 전 아래를 점검:

- [ ] `state/analyzed.json`의 모든 `ai_summary` / `extraction_reason`이 해당 기사 `content_text`에 기반하는지
- [ ] `is_must_know=true` 기사들의 `relevance_score` ≥ 8.0
- [ ] `trend_hashtags` 3~8개
- [ ] `issue_number`가 state.json과 analyzed.json에서 동일
- [ ] `docs/index.html` 업데이트 완료 (성공 케이스)
- [ ] git push 성공
- [ ] 카카오톡 메시지가 `📰 데일리 뉴스 · ...` (성공) 또는 `⚠️ 뉴스 생성 실패` (실패)로 시작

## 5. 요약 한눈에

```
git pull
  ↓
prepare-run --period <오전|오후>
  ↓
collect                                  ← 3회 재시도
  ↓
[Agent] candidates.json → analyzed.json  ← grounded, 3회 재시도
  ↓
mark-stage analyzing
  ↓
render                                   ← 3회 재시도
  ↓
mark-stage deploying
  ↓
git commit & push                        ← 3회 재시도
  ↓
mark-success
  ↓
mark-stage notifying
  ↓
notify-success → MCP 카카오 전송
  ↓
commit state / push / 종료

(단계 어디서든 3회 재시도 모두 실패 시)
  ↓
mark-failure → notify-failure → MCP 카카오 실패 알림 → 종료
```
