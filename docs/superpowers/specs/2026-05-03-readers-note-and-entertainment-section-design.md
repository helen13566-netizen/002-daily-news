# 2026-05-03 READER'S NOTE 단순화 + 연예 섹션 추가 설계

## 배경

사용자(독자) 피드백:

1. **READER'S NOTE 가 너무 어렵다** — 외래어·전문용어("거버넌스 재정의", "락인", "AGI 조항", "엔터프라이즈"), 80자 이상의 복문이 자주 등장한다. agent-prompt.md 에 이미 "독자(일반인·중학생 수준 어휘)" 한 줄이 있으나 LLM 이 이를 잘 따르지 못한다.
2. **연예 뉴스가 빠져있다** — 현재 섹션은 `공식 AI 업데이트 / AI 뉴스 / 종합 뉴스` 셋. agent-prompt 에는 "연예·스포츠 ≤ 4점, 쿼터 채우지 말 것" 규칙으로 의도적 배제. 사용자는 별도 섹션으로 추가 희망.

## 목표

- READER'S NOTE 본문 톤을 중학생도 한 번에 이해할 수 있게.
- `연예` 카테고리를 1급 섹션으로 추가, 매일 약 10건 노출.

## 비목표

- 기존 섹션 (UPDATE / AI / 종합) 의 분류·쿼터 변경 없음.
- 스포츠/루머/가십에 대한 "≤ 4점" 정책은 그대로 유지 (연예만 분리).
- READER'S NOTE 의 정보 깊이는 줄이지 않음 (어휘만 쉽게).

## 변경 A — READER'S NOTE 톤 단순화 (agent-prompt 강화)

코드 변경 없음. `scripts/agent-prompt.md` 의 insights 작성 가이드 블록만 강화한다.

### 추가 규칙

1. **한 문장 80자 이내** (현재 종종 100자 이상의 복문이 나옴).
2. **외래어·약자는 첫 등장 시 괄호로 풀이**:
   - `IPO(주식 상장)`, `AGI(인공일반지능)`, `M&A(인수합병)`, `R&D(연구개발)`
3. **한자어·전문어를 일상어로**:
   - `거버넌스` → `운영 방식` / `회사 운영 구조`
   - `락인` → `한 곳에 묶임`
   - `재정의` → `다시 정함`
   - `잠재적` → `앞으로 가능성이 있는`
   - `가속화` → `빨라짐`
   - `자율성 보장` → `스스로 결정할 수 있게 함`
4. **큰 숫자는 비교 단위 동반**:
   - `130억달러` → `한국 돈 약 18조원, 삼성전자 1년 영업이익 절반 수준`
5. **전/후 예시 한 쌍**을 가이드 안에 직접 박음:
   - 전: "OpenAI 거버넌스의 핵심 축인 마이크로소프트 관계 재정의는 산업 전반의 클라우드·모델 경쟁 구도를 바꿉니다."
   - 후: "OpenAI 와 마이크로소프트가 협력 구조를 새로 정합니다. 이 변화는 클라우드 시장과 AI 모델 경쟁 흐름을 바꿉니다."

## 변경 B — 연예 섹션 추가

### B-1. RSS 피드 (`pipeline/config.py`)

새 카테고리 `entertainment_news` 와 RSS 3개를 추가:

| 매체 | URL | 비고 |
|------|-----|------|
| 연합뉴스 연예 | `https://www.yna.co.kr/rss/entertainment.xml` | GET 200, application/xml |
| 매일경제 연예 | `https://www.mk.co.kr/rss/50400012/` | 200, application/xml |
| 한국경제 연예 | `https://www.hankyung.com/feed/entertainment` | 200, text/xml (네이버 엔터 RSS 미제공으로 대체) |

`default_tz="Asia/Seoul"`, `window_hours=None` (오전/오후 고정 윈도우).

### B-2. 분류 분기 (`pipeline/collect.py`)

`process_feed` 의 카테고리 결정 로직(현재 line 541-544):

```python
if feed.category in ("ai_news", "official_ai", "entertainment_news"):
    category = feed.category
else:
    category = "ai_news" if matched_keywords else "general_news"
```

`entertainment_news` 피드는 키워드 매칭 없이 그대로 통과. AI 키워드는 매치되어도 ai_news 로 승격되지 않음 (피드 카테고리 우선).

### B-3. agent-prompt (`scripts/agent-prompt.md`)

- 새 풀: `ent_pool = [a for a in articles if a["category"]=="entertainment_news"]`
- 출력 sections 에 `"연예 뉴스"` 추가, 쿼터 **10건** (중요한 순으로).
- "연예·스포츠 ≤ 4점, 쿼터 채우지 말 것" 정책에서 **연예 분리** — 연예는 별도 섹션이므로 별도 점수 정책 (스포츠/루머/가십은 여전히 ≤ 4점).
- Phase 추가: `Phase 3.5 — 연예 뉴스 2건씩 × 약 5 chunk` (총 10건). 기존 Phase 1.5(공식 AI) / Phase 2(AI) / Phase 3(종합) 와 동일 구조.
- output category 허용 값에 `entertainment_news` 추가.

### B-4. 템플릿 (`templates/report.html.j2`)

- 카운트 매크로(line 437-446) 에 `'연예' in sec.title` 분기 추가, `ns.ent_count`.
- sec-id 매핑(line 567) 에 `sec-entertainment` 추가.
- 시각적 차이는 없음 — 기존 섹션과 동일 카드 스타일 사용.

## 테스트 전략

새 동작에 대한 RED → GREEN:

1. **`test_process_feed_keeps_entertainment_category`** — `category="entertainment_news"` 인 피드의 기사가 AI 키워드 매치 여부와 무관하게 `entertainment_news` 카테고리로 보존되는지 검증.

기존 28개 collect 테스트 + render/state/run 테스트 회귀 없음.

## 통합 절차

1. TDD 사이클로 코드 변경.
2. main 에 push (사용자 승인 받아 진행).
3. `gh workflow run collect.yml --ref main` — 새 RSS 포함된 candidates.json 생성.
4. `daily-news-evening-kst` routine 즉시 trigger — 카톡으로 brief 도착 (연예 섹션 포함, 쉬운 톤).

## 미해결/추후

- **네이버 엔터 통합**: 사용자가 처음 요청한 `https://m.entertain.naver.com/home` 은 SPA HTML 로 RSS 미제공. 추후 NaverSearch MCP 또는 별도 스크래퍼 path 를 고려할 수 있으나 본 변경의 범위 밖.
- **연예 점수 정책 미세 조정**: 일단 연예는 별도 섹션 분리만 하고 점수 정책은 일반과 동일. 노출 후 카톡으로 보이는 톤이 너무 가십성이면 별도 score 룰 추가 검토.
