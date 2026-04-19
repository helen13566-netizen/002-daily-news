# 뉴스 인사이트 레이어 설계

- 생성일: 2026-04-19
- 대상: `002-daily-news` 파이프라인 v8 위에 "인사이트 레이어"를 추가
- 상위 목적: 독자가 뉴스를 "그냥 읽고 끝"이 아니라, **세상을 바라보는 판단 근육**을 기르도록 돕는 2차 레이어 제공

## 1. 현재 상태와 문제

### 현재
- `analyzed.json` 각 기사에 `extraction_reason` (40~80자, grounded) 하나만 있음
- 카드 UI의 `.why` 박스에 고정 표시

### 문제
- `extraction_reason`이 짧고 원문 범위 안에서만 생성되어 **"왜 이 기사를 봐야 하는지"가 피상적**으로 들림
- 독자가 뉴스를 보고 **"그래서 어쩌라고?"** 에 답을 얻지 못함
- 뉴스 독해·판단 훈련을 돕는 관점이 전혀 없음

## 2. 목표

독자가 한 기사 카드를 열면 다음을 알게 된다:

1. **이 기사가 나·사회·산업에 실제로 어떻게 영향을 미치는지** (파급효과)
2. **과거 비슷한 일은 어떻게 됐는지** (역사·비교)
3. 기사 성격에 따라 추가로:
   - **내가 뭘 해야/주의해야 하는지** (개인 조언)
   - **앞으로 어떻게 전개될 수 있는지** (시나리오)
   - **이 뉴스를 어떤 질문으로 비판적으로 읽어야 하는지** (사고 프레임)
   - **여러 입장에서 어떻게 다르게 보이는지** (다관점)

### Non-goals
- 기사 원문 번역/재구성 (이미 `ai_summary` 가 담당)
- 뉴스 팩트체크 자동화 (별도 영역)
- 추천 액션의 자동 실행 (정보 제공에 한정)

## 3. 페르소나

Agent에게 주입할 프리앰블:

> 너는 정치·경제·국제 정세를 오래 다뤄온 시니어 뉴스 편집장이다. 뉴스 리터러시 원칙(1차 출처 확인, 이해관계자 매핑, 인과-상관 분리, 사실·해석·추측 구분, 선례 분석)을 체화했다. 목표는 독자의 판단 근육을 훈련시키는 것. 단정하지 말고, 불확실한 부분은 "~할 가능성이 있다", "~일 수 있습니다" 로 표현하라.

## 4. 문체 규칙

**대상 독자**: 뉴스를 처음 접하는 사람, 중학생 수준 어휘까지.

| 규칙 | 적용 예 |
|------|---------|
| 전문용어·약어 풀어쓰기 | "CPI" → "소비자물가(마트에서 사는 물건 값 지수)" |
| 한자어·외래어 대체 | "파급효과" → "연쇄 영향" / "시나리오" → "어떻게 전개될지" |
| "→" 화살표 대신 서술 문장 | "A → B → C" → "A가 일어나면 B가 되고, 그러면 결국 C까지 영향을 줍니다" |
| 수치는 감각적 비유 동반 | "10%" → "10명 중 1명 / 만 원 중 천 원 수준" |
| 능동태·짧은 문장 (40~60자) | "~이 증가했다" → "~이 늘었어요" |
| 독자 공감 어투 | "우려된다" → "걱정되는 부분은~" |

각 인사이트 문단: **2~4문장, 120~220자**.

### 헤딩 톤
- `📡 이게 우리한테 어떻게 영향을 줄까?` (파급효과)
- `🗂 예전에도 이런 일이 있었을까?` (역사·비교)
- `🔮 앞으로 어떻게 될 수 있을까?` (시나리오)
- `💡 나는 뭘 해야 할까?` (개인 조언)
- `🧐 이 뉴스, 이렇게 읽어보세요` (사고 프레임)
- `👥 입장이 다르면 어떻게 보일까?` (다관점)

## 5. 인사이트 축 6종

### 기본 2축 (모든 기사에 시도)

**C. 파급효과** — 이 사건이 **2차·3차 연쇄로** 다른 산업·국가·계층에 어떻게 퍼지는지. 서술형으로 풀어서 설명.

**D. 역사·비교** — **유사한 과거 사례**와 비교, 그때의 결과·차이점. 다른 나라 사례 포함.

### 보너스 축 (AI 판단으로 추가 or 교체)

**A. 개인 조언** — "내가 지금 뭘 하면 좋을까"에 대한 구체 행동 지침. 단, 금융 상품 구체 매수·매도 추천은 하지 말고 "검토해볼 만한 포인트" 수준.

**B. 시나리오** — 최선·최악·중간 전개와 갈림점. 가능성의 크기를 "높음/중간/낮음" 정도로 수식.

**E. 사고 프레임** — 독자가 이 뉴스를 비판적으로 읽기 위해 던져야 할 질문들. "이 수치의 1차 출처는?", "반대 입장의 수치는?", "보도 시점은 왜 지금?".

**F. 다관점** — 같은 사건을 정부·기업·노동자·소비자·국제사회 입장에서 본다면 어떻게 다른지.

### 축 선택 가이드라인 (agent-prompt 에 명시)

| 기사 유형 | 기본 유지 | 추가 후보 | 교체 권장 |
|-----------|----------|----------|-----------|
| 국제·외교·분쟁 | C + D | B 시나리오 | — |
| 통화·금리·부동산 | C + D | A 개인 | — |
| 기업 M&A·사업 구조 | C + D | F 다관점, B 시나리오 | — |
| AI·기술 신제품 | C + D | A 개인 | — |
| 재난·안전·의료 | C + D | A 개인 | — |
| 정치 논란·숫자 출처 모호 | D | E 사고 프레임 | **C → E 교체** |
| 연예·스포츠·단순 속보 | (분석 대상 아님, score ≤ 4 → must_know 제외) | — | — |

기사당 총 축 수: **2~4개**.

## 6. analyzed.json 스키마 확장

```jsonc
{
  "issue_number": 7,
  "generation_timestamp": "2026-04-19T18:00:00+09:00",
  "trend_hashtags": [...],
  "articles": [
    {
      "article_id": "...",
      "title": "...",
      "source": "...",
      "published_at": "...",
      "original_url": "...",
      "content_text": "...",
      "category": "ai_news | general_news",
      "keywords": [...],
      "ai_summary": "<원문 grounded 요약, 140~220자>",
      "extraction_reason": "<40~80자, 기존 유지, grounded>",
      "relevance_score": 8.5,
      "is_must_know": true,
      "insights": {
        "ripple": {
          "title": "이게 우리한테 어떻게 영향을 줄까?",
          "icon": "📡",
          "text": "<120~220자, 서술형, 쉬운 말>"
        },
        "history": {
          "title": "예전에도 이런 일이 있었을까?",
          "icon": "🗂",
          "text": "<120~220자>"
        },
        "bonus": [
          {
            "type": "personal | scenario | frame | perspective",
            "title": "<헤딩>",
            "icon": "💡 | 🔮 | 🧐 | 👥",
            "text": "<120~220자>"
          }
        ]
      }
    }
  ]
}
```

### 하위 호환
- `insights` 필드가 없는 기존 기사는 렌더러가 **폴백**으로 기존 `.why` 박스만 표시 (insight 블록 없음).
- 따라서 과거 archive HTML 은 그대로 동작.

## 7. UI 설계

### HTML 구조 변경

기존 `.why` 박스를 `<details>/<summary>` 로 래핑. JavaScript 없이 HTML 표준 토글 동작.

```html
{% if article.insights %}
<details class="why-insights">
  <summary class="why">
    <strong>추출이유</strong> {{ article.extraction_reason }}
    <span class="expand-hint" aria-hidden="true">▾</span>
  </summary>
  <div class="insights-body">
    <div class="insight" data-axis="ripple">
      <h4>{{ article.insights.ripple.icon }} {{ article.insights.ripple.title }}</h4>
      <p>{{ article.insights.ripple.text }}</p>
    </div>
    <div class="insight" data-axis="history">
      <h4>{{ article.insights.history.icon }} {{ article.insights.history.title }}</h4>
      <p>{{ article.insights.history.text }}</p>
    </div>
    {% for b in article.insights.bonus %}
    <div class="insight" data-axis="{{ b.type }}">
      <h4>{{ b.icon }} {{ b.title }}</h4>
      <p>{{ b.text }}</p>
    </div>
    {% endfor %}
  </div>
</details>
{% else %}
<div class="why">
  <strong>추출이유</strong> {{ article.extraction_reason }}
</div>
{% endif %}
```

### CSS (기존 .why 유지 + 신규 블록)

```css
/* summary 가 기존 .why 와 똑같이 생기도록 */
.why-insights > summary.why {
  cursor: pointer;
  list-style: none; /* 기본 삼각형 제거 */
  position: relative;
}
.why-insights > summary.why::-webkit-details-marker { display: none; }
.why-insights > summary.why .expand-hint {
  margin-left: 8px;
  color: var(--accent);
  transition: transform 0.2s;
  display: inline-block;
}
.why-insights[open] > summary.why .expand-hint { transform: rotate(180deg); }

/* 펼침 블록 */
.why-insights .insights-body {
  margin-top: 10px;
  padding: 12px 14px;
  background: rgba(255, 165, 0, 0.04);
  border-left: 2px solid var(--accent);
  border-radius: 0 3px 3px 0;
}
.why-insights .insight { margin-bottom: 14px; }
.why-insights .insight:last-child { margin-bottom: 0; }
.why-insights .insight h4 {
  font-size: 13px;
  color: var(--accent);
  font-weight: 500;
  margin-bottom: 4px;
  letter-spacing: 0;
}
.why-insights .insight p {
  font-size: 13.5px;
  color: var(--text);
  line-height: 1.7;
}
```

### 접근성
- `<details>` 는 키보드 Enter/Space 로 토글 가능 (표준)
- `aria-hidden="true"` 는 데코용 `▾` 에만

## 8. Agent Prompt 변경 (v9)

`scripts/agent-prompt.md` 에 다음을 추가:

### (신설) 단계 D' — 인사이트 생성 원칙

```
각 기사의 analyzed 객체에 `insights` 필드를 포함한다.

[필수]
- ripple (파급효과), history (역사·비교) 두 축은 기본 시도.
- 각 텍스트는 120~220자, 서술형 2~4문장, 중학생 수준 어휘.
- 전문용어 사용 시 괄호로 풀어쓰기.
- 수치는 "10명 중 1명", "만 원 중 천 원 수준" 같은 감각적 비유 동반.

[페르소나]
시니어 편집장 관점. 독자의 판단 근육 훈련이 목적. 단정 금지.

[보너스 축 선택 규칙]
- 기사가 통화·금리·부동산·의료·IT 신제품 → A 개인 조언 추가
- 기사가 기업 M&A·산업 재편 → F 다관점 추가, B 시나리오 추가
- 기사가 국제 분쟁·외교 → B 시나리오 추가
- 기사 숫자 출처가 모호하거나 단일 출처 정치 논란 → C 교체 → E 사고 프레임
- 연예/스포츠/단순 속보 → insights 생략 (실제로 must_know 에서도 제외)

[분량·시간 예산 (v8 효율 수칙 연장)]
- 한 기사 insight 전체가 800자를 넘지 않도록.
- 50건 전체 inflation 고려: content_text 를 다 읽는 대신 title + ai_summary + keywords 로 1차 판단, 보너스 축은 필요 시에만.
```

### grounded 제약 조정

- `ai_summary` / `extraction_reason`: **기존 grounded 유지** (원문 범위 내)
- `insights.ripple` / `insights.history` / `insights.bonus[].text`: **grounded 완화**. agent가 가진 상식·선례 지식으로 해석 가능하되, 사실이 아닌 추정은 "~일 가능성이 높습니다" 같은 모달로 명시.

## 9. 변경 파일 목록

| 파일 | 변경 내용 |
|------|----------|
| `scripts/agent-prompt.md` | v9: 단계 D' 추가, insights 스키마·문체·선택 규칙 명시 |
| `templates/report.html.j2` | `.why` 박스를 `<details>` 로 래핑, insights-body 추가, CSS 신규 블록 |
| `pipeline/render.py` | 하위호환 로직(insights 없으면 폴백), 템플릿 변수 전달 |
| `tests/test_render.py` | insights 유/무 렌더 테스트 케이스 추가 |
| `docs/superpowers/specs/2026-04-19-news-insight-layer-design.md` | 본 문서 (신규) |

## 10. 테스트 전략

1. **렌더 단위 테스트**:
   - insights 포함 analyzed.json → `<details>` 태그 존재, insight 블록 렌더
   - insights 없음 → 기존 `.why` 박스만 렌더 (하위호환)
   - bonus 배열 여러 개 → 각각 렌더

2. **시각 회귀 (smoke)**:
   - 샘플 기사 5건으로 로컬 render → HTML 열어 토글 동작·색상 확인

3. **프로덕션 검증**:
   - agent 수동 run 1회 → 브라우저에서 카드 클릭 → insights 펼쳐지는지
   - 카카오 메시지는 변경 없음 (성공 메시지 템플릿 유지)

## 11. 롤백 플랜

- insights 필드는 **옵션**. 빠지면 자동 폴백 → 기존 UI 유지.
- 문제 발생 시 agent-prompt 에서 `insights` 지시만 제거하면 v8 상태로 자연 회귀.
- 템플릿은 `{% if article.insights %}` 분기라 양쪽 모두 지원.

## 12. 성공 기준

- 독자가 카드를 열고 인사이트를 읽은 뒤 **"아 그래서 이게 중요한 거구나"** 를 체감
- 전문용어 검사: 중학생 수준으로 읽기 가능한 어휘 비율 ≥ 90%
- 각 insight 문단 120~220자, 서술형 2~4문장 유지율 ≥ 90%
- must_know 기사에 insights 실패(빠짐) 비율 ≤ 10%
- session timeout 재발하지 않음 (v8 효율 수칙 준수 하에 50건 분석이 제한 시간 내)
