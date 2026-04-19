# 뉴스 리터러시·의사결정론 레퍼런스 (v1)

- 수집일: 2026-04-19
- 용도: 데일리 뉴스 브리핑 agent 의 인사이트 생성 품질을 **공신력 있는 방법론 기반**으로 업그레이드하기 위한 레퍼런스 모음.
- 후속: 각 축별 프레임워크 매핑(`docs/research/axis-framework-map.md`) → agent-prompt v13 통합.

---

## 1. Stanford Civic Online Reasoning (COR)

**출처**: Stanford History Education Group → Digital Inquiry Group
**URL**: https://cor.inquirygroup.org/

### 3 핵심 질문 (Three Moves)
뉴스·정보를 읽을 때 가장 먼저 던져야 할 세 질문:

1. **"Who is behind this information?"** — 누가 만들었나
2. **"What is the evidence?"** — 어떤 근거가 있는가
3. **"What do other sources say?"** — 다른 출처는 어떻게 말하는가

### Lateral Reading (옆으로 읽기)
기사 안에서만(수직 읽기) 판단하지 않고, **새 탭을 열어 그 출처·저자를 다른 신뢰 가능한 사이트에서 조회**. 팩트체커들이 실제로 쓰는 방식. 일반 독자가 가장 자주 놓치는 행동.

### Click Restraint (클릭 자제)
검색 결과 맨 위를 바로 누르지 말고, 여러 결과를 훑은 뒤 가장 신뢰 가능한 것을 선택. 가장 상단 = 가장 신뢰도는 아님.

**우리 파이프라인 적용**: `frame` (사고 프레임) 축에서 "이 뉴스를 읽을 때 이런 질문을 던져보세요" 체크리스트로 주입.

---

## 2. IMVAIN — News Literacy Project (Stony Brook)

**출처**: Center for News Literacy, Stony Brook University School of Journalism
**URL**: https://digitalresource.center/content/introducing-imvain

### 개별 출처 평가 5축
좋은 출처 vs 나쁜 출처를 판단하는 기준. 이니셜 암기법:

| 약자 | 기준 | 좋은 출처 |
|------|------|-----------|
| **I** | Independent vs Self-interested | 이해관계 없음 |
| **M** | Multiple vs Lone | 여러 출처 교차 확인 |
| **V** | Verifies vs Asserts | 검증 가능한 정보 제공 |
| **A** | Authoritative/Informed vs Uninformed | 해당 분야 권위·전문성 |
| **N** | Named vs Unnamed | 실명 책임 |

**우리 파이프라인 적용**: `frame` 축의 "숫자·인용의 출처가 어떤 출처인가" 점검. 정치 논란 기사에서 특히 필수.

---

## 3. Tetlock Superforecasting

**출처**: Philip E. Tetlock, Dan Gardner, "Superforecasting: The Art and Science of Prediction" (2015)
**URL**: https://goodjudgment.com/philip-tetlocks-10-commandments-of-superforecasting/

### 10 Commandments 요약 (핵심만)

1. **Triage**: 쉬운(운명적) 질문·어려운(혼돈) 질문 피하고 **노력이 보상받는 골디락스 영역** 집중.
2. **Break hard problems into tractable sub-problems**: 큰 질문을 작은 답 가능한 조각으로 분해.
3. **Strike the right balance between inside and outside views**: 구체 사례(inside) + 유사 사례 통계(outside) 양쪽에서.
4. **Strike the right balance between under- and overreacting to evidence**: 증거에 과잉/과소 반응 피하기. **벨리프 업데이트는 치실·양치처럼 일상적으로**.
5. **Look for clashing causal forces at work**: 상반되는 인과 힘을 동시에 보기.
6. **Strive to distinguish as many degrees of doubt as the problem permits**: 이분법이 아니라 **5~10단계 확신 등급**으로 구분.
7. **Strike the right balance between under- and overconfidence**: 자신감 캘리브레이션.
8. **Look for the errors behind your mistakes but beware of rearview-mirror hindsight biases**: 과거 실수에서 배우되 사후편향 경계.
9. **Bring out the best in others and let others bring out the best in you**: 팀 단위 앙상블 사고.
10. **Master the error-balancing bicycle**: 실전 반복으로 학습.

### 핵심 키워드
- **Outside view / Inside view** — 유사 사례 통계(outside) 와 이 사건 고유 맥락(inside) 균형
- **Comparison class** — 어떤 "사례 집합"에 속하는지 정의
- **Belief updating** — 새 증거마다 사전 확률 조정 (Bayesian)
- **Probabilistic thinking** — "확실·불확실" 이 아니라 **확률 분포**

**우리 파이프라인 적용**: `history` 축에서 "유사 사례와의 비교 + base rate" 로, `scenario` 축에서 "확률 언어" 로.

---

## 4. Entman Framing Theory (1993)

**출처**: Robert M. Entman, "Framing: Toward Clarification of a Fractured Paradigm" (Journal of Communication, 1993)
**URL**: https://onlinelibrary.wiley.com/doi/10.1111/j.1460-2466.1993.tb01304.x

### Framing 정의
> "To frame is to **select some aspects of a perceived reality and make them more salient** in a communicating text, in such a way as to promote a particular problem definition, causal interpretation, moral evaluation, and/or treatment recommendation."

같은 사건도 **어떤 면을 부각시키느냐**에 따라 해석이 달라짐. 뉴스는 본질적으로 frame 된 것.

### 4 Functions of Framing
모든 뉴스 프레임이 아래 4개 기능 중 2개 이상을 수행:

1. **Problem Definition** — 이 사건을 "어떤 문제"로 규정하는가
2. **Causal Interpretation** — 원인을 어디에 귀속하는가
3. **Moral Evaluation** — 도덕적 판단을 어떻게 유도하는가
4. **Treatment Recommendation** — 어떤 해결책을 제안하는가

### 핵심 통찰
동일 사건을 다른 frame 으로 보면 **다른 이해관계자의 목소리**가 드러남. 예: "삼성 노조 파업" 을 "경제 손실 1조" frame 으로 보면 경영진 관점, "성과 배분" frame 으로 보면 노동자 관점, "반도체 경쟁력" frame 으로 보면 국가 관점.

**우리 파이프라인 적용**: `perspective` (다관점) 축에서 "같은 사건을 A 측·B 측·C 측은 어떻게 프레이밍하는가". `frame` 축에서 "이 기사가 선택한 프레임은 무엇이고, 빠진 프레임은 무엇인가".

---

## 5. Donella Meadows 시스템 사고

**출처**: Donella Meadows, "Thinking in Systems: A Primer" (2008), "Leverage Points: Places to Intervene in a System"
**URL**: https://donellameadows.org/archives/leverage-points-places-to-intervene-in-a-system/

### Iceberg Model — 4 Levels
뉴스 = 빙산의 일각. 수면 아래가 훨씬 중요.

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
            🗞️ Events
      "이 기사의 사건" (눈에 보임)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
            📈 Patterns
      "반복되는 흐름·트렌드"
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
            🏛️ Structures
      "제도·법·경제 구조·권력 배치"
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
            🧠 Mental Models
   "사회·권력자·대중의 믿음·전제"
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

사건 해석 시 **"이 사건은 어느 레벨 변화를 말하고 있는가"** 질문. 많은 기사는 Events 레벨만 보도 → 독자가 Patterns/Structures/Mental Models 까지 깊이 가야 이해됨.

### 12 Leverage Points (높은 효과 순)
Meadows 가 제시한 시스템 개입 지점 12가지 (낮은 → 높은):

12. Constants, parameters, numbers (숫자)
11. Sizes of buffers (완충 규모)
10. Structure of material stocks and flows
9. Length of delays
8. Strength of negative feedback loops
7. Gain of positive feedback loops
6. Structure of information flows
5. Rules of the system (incentives, punishments, constraints)
4. Power to add, change, evolve system structure
3. **Goals of the system**
2. **Mindset/paradigm out of which the system arises**
1. **Power to transcend paradigms**

숫자 조정 (12) 은 쉽지만 효과 낮고, 패러다임 전환 (1-3) 은 어렵지만 효과 큼. 뉴스 분석 시 "이 사건은 어느 레버리지에 영향?" 질문.

**우리 파이프라인 적용**: `ripple` 축에서 Iceberg Model 기반 4레벨 분석 + "이 사건은 Events 레벨인가, Structures 레벨인가". `scenario` 축에서 "어느 레버리지를 건드리는 해결책인가".

---

## 6. Stakeholder Mapping

**출처**: 공공관계·저널리즘 교재, Stakeholder Analysis 공통 프레임워크
**URL**: https://pressbooks.bccampus.ca/publicrelations/chapter/chapter-5/

### 기본 분류
- **Primary** — 직접 영향받는 집단 (예: 노조 파업 기사 → 노동자, 경영진)
- **Secondary** — 간접 영향받는 집단 (소비자, 하청업체, 주주)
- **Key** — 사건을 좌우할 수 있는 권력·자원 보유자 (정부, 규제기관)

### 2×2 Matrix (Power × Interest)
| | 관심 낮음 | 관심 높음 |
|---|---|---|
| **권력 높음** | 만족시키기 | 긴밀히 협력 |
| **권력 낮음** | 모니터링 | 정보 제공 |

### 뉴스 적용
한 기사에 **최소 3~5개 stakeholder**를 식별. 각 stakeholder 의 입장·이해·반응 예측. "이 사건이 A 에게는 호재, B 에게는 악재" 구조가 거의 항상 있음.

**우리 파이프라인 적용**: `perspective` (다관점) 축의 구조적 기반. 정부·기업·노동자·소비자·국제사회 5대 stakeholder 기본 프레임.

---

## 7. Reference Class Forecasting / Base Rate

**출처**: Daniel Kahneman, Amos Tversky (1974, 1979)
**URL**: https://en.wikipedia.org/wiki/Reference_class_forecasting

### Base Rate Neglect
사람들은 **사건 자체의 통계적 빈도(base rate)** 를 무시하고 **개별 사례의 구체 특징** 으로 판단하는 경향. Kahneman·Tversky 의 대표 발견.

예: "이 스타트업은 특별하니까 10년 안에 유니콘 될 확률 90%" — 기저율(전체 스타트업의 10년 유니콘 전환율 ~0.1%) 무시.

### Inside View vs Outside View
- **Inside view**: 이 사건의 구체 맥락·디테일 기반 예측. **낙관 편향 강함**.
- **Outside view**: 유사 사례 집합의 실제 결과 분포 기반 예측. **현실적**.

의사결정·예측 시 **Outside View 를 먼저** 잡고 Inside View 로 조정.

### Reference Class 정의 방법
1. 이 사건과 유사한 과거 사례 집합 특정
2. 그 집합의 실제 결과 분포 조사
3. 이 사건이 그 분포의 어디쯤인지 위치

**우리 파이프라인 적용**: `history` 축의 핵심 로직. "비슷한 일이 있었다" 를 넘어서 **"그 사례들의 결과 분포"** 를 말하게.

---

## 8. IFCN Code of Principles (팩트체크)

**출처**: International Fact-Checking Network @ Poynter
**URL**: https://ifcncodeofprinciples.poynter.org/

### 5 Commitments
팩트체크 조직이 지켜야 할 원칙. 뉴스를 읽는 독자에게는 "이 기사의 방법론을 어떻게 검증하나" 체크리스트로 역적용 가능.

1. **Commitment to Nonpartisanship and Fairness** — 당파성 없음, 동일 기준
2. **Commitment to Transparency of Sources** — 출처 공개, 독자가 재검증 가능
3. **Commitment to Transparency of Funding and Organization** — 자금·조직 투명성
4. **Commitment to Transparency of Methodology** — 방법론 공개
5. **Commitment to Open and Honest Corrections** — 오류 정정 공개

**우리 파이프라인 적용**: `frame` 축의 "이 기사는 어떤 출처·자금·방법론에 기반? 검증 가능한가" 체크.

---

## 9. Matt Levine 스타일 (Incentive-Based Analysis)

**출처**: Matt Levine, "Money Stuff" (Bloomberg Opinion 뉴스레터, 2013~)
**URL**: https://www.bloomberg.com/authors/ARbTQlRLRjE/matthew-s-levine

### 핵심 스타일
- **"Incentives explain more than rhetoric"** — 누가 뭐라고 말하든 **그의 경제적·구조적 유인**이 행동을 설명
- **Markets as architecture** — 시장·제도를 "건물 설계도" 처럼 분석
- **First principles + concrete case** — 일반 원리 → 구체 뉴스 적용
- **Honest humor** — 복잡한 걸 과장/겸손 섞인 톤으로 쉽게 풀이

### 질문 템플릿
1. **누가 이익 보는가?** (who wins)
2. **누가 손해 보는가?** (who loses)
3. **왜 지금 이 행동을 하는가?** (incentive alignment)
4. **이 주장을 하는 사람의 이해관계는?** (disclosure)

**우리 파이프라인 적용**: `personal` (개인 조언) 축에서 "이 뉴스에서 어떤 유인이 작동 중인지 알면, 내가 이렇게 행동·대비할 수 있다". `perspective` 축에서 "누가 이익·손해 보는가" 구조화.

---

## 10. Second-/Third-Order Consequences

**출처**: 시스템 사고·Howard Marks·Ray Dalio 공통 개념
**URL**: https://fs.blog/second-order-thinking/

### 개념
- **1차 효과**: 즉각·직접 결과 (눈에 보임)
- **2차 효과**: 1차 결과의 파급 (시간 지나 나타남, 종종 1차와 반대 방향)
- **3차 효과**: 2차 결과가 시스템 균형을 재편하며 새 평형 형성

### "And then what?" 질문
고정밀 예측자들은 매 단계마다 **"그 다음엔?"** 을 묻는 습관. 대부분의 뉴스 보도는 1차 효과만 언급.

예: "금리 인상" 기사
- **1차**: 대출 이자 오름
- **2차**: 소비 위축 → 기업 매출↓ → 고용↓
- **3차**: 실업·체감경기 악화 → 정치적 압력 → 금리 되돌림 검토

**우리 파이프라인 적용**: `ripple` 축의 "그 다음엔?" 을 **3단계까지** 강제 질문.

---

## 레퍼런스 출처 목록

| # | 프레임워크 | 공식 URL |
|---|-----------|----------|
| 1 | Stanford COR | https://cor.inquirygroup.org/ |
| 2 | IMVAIN / Stony Brook | https://digitalresource.center/content/introducing-imvain |
| 3 | Tetlock Superforecasting | https://goodjudgment.com/philip-tetlocks-10-commandments-of-superforecasting/ |
| 4 | Entman Framing | https://onlinelibrary.wiley.com/doi/10.1111/j.1460-2466.1993.tb01304.x |
| 5 | Meadows Systems | https://donellameadows.org/archives/leverage-points-places-to-intervene-in-a-system/ |
| 6 | Stakeholder Mapping | https://pressbooks.bccampus.ca/publicrelations/chapter/chapter-5/ |
| 7 | Base Rate / Reference Class | https://en.wikipedia.org/wiki/Reference_class_forecasting |
| 8 | IFCN Fact-Checking | https://ifcncodeofprinciples.poynter.org/ |
| 9 | Matt Levine | https://www.bloomberg.com/authors/ARbTQlRLRjE/matthew-s-levine |
| 10 | 2nd/3rd Order | https://fs.blog/second-order-thinking/ |

---

## 다음 단계

1. **축별 프레임워크 매핑** (`docs/research/axis-framework-map.md`) — 6개 인사이트 축에 위 10개 프레임워크를 매핑
2. **Agent-prompt v13 통합 설계** — stream idle timeout 예산(v12 검증됨) 안에서 어떻게 주입할지
3. **설계 문서 작성** → writing-plans → 구현
