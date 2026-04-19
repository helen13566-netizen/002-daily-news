# 뉴스 인사이트 품질 업그레이드 v13 설계

- 작성일: 2026-04-19
- 베이스: v12 (3건 chunk 20회, 6축 구조 — 운영 중)
- 목적: 공신력 있는 뉴스 리터러시·의사결정론 프레임워크 10종을 축별 체크리스트로 agent-prompt 에 주입해 인사이트의 **분석 품질** 업그레이드
- 레퍼런스: `docs/research/news-literacy.md`, `docs/research/axis-framework-map.md`

## 1. 문제 정의 (v12 한계)

현재 v12 는 "시니어 편집장 페르소나 + 중학생 어휘 + grounded 제약" 만으로 인사이트 생성. 글의 **톤과 형식**은 잘 잡히지만, **분석의 구조적 깊이**는 agent 의 사전 지식에 100% 의존. 결과:

- `ripple`: 1~2차 연쇄에서 끝남, 3차 효과 거의 없음
- `history`: "비슷한 일 있었다" 수준, reference class 의 결과 분포 부재
- `scenario`: "~일 수 있다" 추정, 확률 등급 구분 부족
- `personal`: 막연한 조언, 구체 행동 체크리스트 부족
- `frame`: "질문 던져라" 수준, COR·IMVAIN·IFCN 같은 체계적 방법론 부재
- `perspective`: stakeholder 가 뭉뚱그려짐, 체계적 식별·매핑 부재

## 2. 해결 접근

### 원칙
- **분량 증가 최소화** (stream idle timeout 재발 방지)
- **프레임워크 자체는 agent 가 이미 학습된 내용** (별도 RAG 불필요)
- Agent-prompt 에는 **각 축별 2~3줄 체크리스트**만 inline 주입
- 상세 레퍼런스는 저장소 문서로 보존해 향후 개선·디버깅 시 참고

### 도구
- Agent-prompt v13 = v12 + **축별 체크리스트 6개 블록** (각 2~3줄)
- 기존 chunk 분할(3건 × 20회) 구조 그대로 유지
- UI·render·notify 변경 없음

## 3. 적용 프레임워크 (10종)

자세한 내용은 `docs/research/news-literacy.md`.

| # | 프레임워크 | 주 적용 축 |
|---|-----------|-----------|
| 1 | Stanford COR (3 moves · Lateral reading · Click restraint) | `frame` |
| 2 | IMVAIN (Independent · Multiple · Verifies · Authoritative · Named) | `frame` |
| 3 | Tetlock Superforecasting (10 commandments, probability grading) | `scenario`, `history` |
| 4 | Entman Framing (Problem·Cause·Moral·Treatment) | `perspective`, `frame` |
| 5 | Meadows Systems (Iceberg model · 12 Leverage points) | `ripple` |
| 6 | Stakeholder Mapping (Primary·Secondary·Key 3-tier) | `perspective` |
| 7 | Reference Class Forecasting (Base rate · Outside/Inside view) | `history` |
| 8 | IFCN 5 Commitments (Nonpartisan · Transparency · Methodology) | `frame` |
| 9 | Matt Levine Incentive Analysis (Who wins/loses · Why now) | `personal`, `perspective` |
| 10 | Second/Third-Order Consequences ("And then what?") | `ripple`, `scenario` |

## 4. Agent-prompt v13 변경 사항

`scripts/agent-prompt.md` 의 인사이트 레이어 섹션 안에 다음을 추가·수정:

### 4.1 페르소나 확장

**변경 전**:
> 너는 정치·경제·국제 정세를 오래 다뤄온 시니어 뉴스 편집장이다. 1차 출처, 이해관계자 매핑, 인과-상관 분리, 사실·해석·추측 구분, 선례 분석에 익숙하다.

**변경 후 (v13)**:
> 너는 정치·경제·국제 정세를 오래 다뤄온 시니어 뉴스 편집장 겸 체계적 분석가다. Stanford Civic Online Reasoning, Stony Brook IMVAIN, Tetlock Superforecasting, Meadows Systems Thinking(Iceberg · Leverage Points), Entman Framing, Kahneman Reference Class Forecasting, IFCN fact-checking 원칙을 훈련받았다. 단정하지 말고 "~할 가능성이 높다/중간/낮다" 같은 확률 등급으로 표현하라. 각 축별 아래 체크리스트를 반드시 수행한 뒤 서술해라.

### 4.2 축별 체크리스트 블록 추가

기존 축 설명 뒤에 다음 블록 신설:

```markdown
##### 각 축별 분석 체크리스트 (v13)

각 축의 text 를 작성하기 전에 반드시 **속으로** 아래 체크리스트를 수행하고, 결과를 text 에 녹여라 (체크리스트 자체를 text 로 나열하지 말 것).

**`ripple` (Meadows Iceberg + Second/Third Order)**
- 이 사건이 일으키는 1차·2차·3차 효과를 "그 다음엔?" 질문으로 연쇄
- 이것은 Event 레벨 변화인가 · Pattern 인가 · Structure 인가

**`history` (Reference Class Forecasting)**
- 이 사건이 속한 reference class 정의 (2~3개 유사 과거 사례)
- 그 집합의 실제 결과 분포 + 이번이 어디쯤 위치
- 이번이 과거와 다른 변수 1~2개

**`scenario` (Tetlock Superforecasting)**
- 최선/중간/최악 시나리오 각각의 확률 등급 (높음·중간·낮음)
- "가장 가능성 높은 시나리오" 를 명시
- 다음 며칠~몇 주 안에 어떤 이벤트가 방향을 결정하는가 (갈림길)

**`personal` (Matt Levine Incentive)**
- 이 뉴스에서 누가 이익/손해? (incentive 구조)
- 독자 포지션별(예: 주담대 차주·투자자·직장인) 구체 행동 2~3개 (검토·비교·관찰 수준, 매수·매도 직접 지시 금지)
- 반사적으로 하기 쉬운 **피해야 할 행동 1개**

**`frame` (Stanford COR + IMVAIN + IFCN + Entman)**
- 이 기사 1차 출처 점검: 독립·복수·검증·권위·실명(IMVAIN) 중 약한 부분
- 다른 매체는 어떻게 보도 (lateral reading)
- 이 기사가 택한 frame 은? 빠진 frame 은?
- 독자가 던질 질문 2~3개

**`perspective` (Stakeholder Mapping + Entman 4 functions)**
- 최소 3~5 명의 stakeholder 식별 (Primary·Secondary·Key)
- 각 측이 이 사건을 어떤 문제로 규정하고, 어떤 해결을 원하나 (Entman Problem·Treatment)
- 구조적 갈등 지점 (누가 이익·누가 손해)
```

### 4.3 분량 가이드 조정

- 기존 "120~220자" 유지. 체크리스트는 **내면 분석용**이고 text 에 명시 안 함.
- 단, text 안에 **근거를 드러내는 구체 단서**는 있어야 함 (예: "비슷한 일이 네 번 있었어요" = reference class, "1조 손실 vs 5.4억 성과급" = incentive, "1차 출처가 한 관계자 단일 발언" = IMVAIN M·N 점검).

## 5. 변경 파일

| 파일 | 변경 |
|------|------|
| `scripts/agent-prompt.md` | v13: 페르소나 확장 + 축별 체크리스트 블록 |
| `docs/research/news-literacy.md` | 이미 작성 (레퍼런스 10종 상세) |
| `docs/research/axis-framework-map.md` | 이미 작성 (축 × 프레임워크 매핑) |
| `docs/superpowers/specs/2026-04-19-news-insight-quality-v13-design.md` | 이 문서 |

render/notify/config/테스트: **변경 없음**.

## 6. 리스크 · 검증

### 리스크
- 프롬프트 분량 증가(~500자) → 매 LLM 호출마다 context 소비 증가.
- v12 의 stream idle timeout 재발 가능성 **낮음** (chunk 크기는 변경 없음, 프롬프트 크기 증가는 응답 크기 증가보다 영향 작음).
- 체크리스트가 너무 많아서 agent 가 과부하로 품질이 떨어질 가능성. 완화: text 에는 **결과만** 드러내고 체크리스트 자체는 속으로 수행하도록 명시.

### 검증
1. **로컬 테스트**: LLM 호출 필요하여 운영에서 검증
2. **운영 검증**: 오전·오후 trigger 각 1회 수동 실행 → 인사이트 text 에서 다음 단서 관찰
   - `ripple`: "1차·2차·3차", "그 다음엔", Iceberg 레벨 언급
   - `history`: "N 번 있었어요", "결과는 평균 X%" 같은 집합 표현
   - `scenario`: "가능성 높음/중간/낮음", "갈림길"
   - `personal`: 구체 행동 2개 이상 + 피해야 할 행동
   - `frame`: 출처·수치·교차확인 언급
   - `perspective`: 3+ stakeholder 명시

### 폴백
품질 악화(agent가 체크리스트에 매몰되어 읽기 어려운 text 생성) 시:
- v12 로 즉시 되돌리기 (agent-prompt.md 단일 파일 revert)
- 점진적 완화 (체크리스트 일부만 유지)

## 7. 성공 기준

- 6축 text 에서 위 단서들이 **축당 최소 1개 이상** 관찰
- 기존 v12 의 문체(중학생 어휘·서술형·120~220자) 유지
- stream idle timeout 재발 없음 (실행 시간 20~30분 내)
- 사용자가 체감상 "전문성 있다" 판단

## 8. 타임라인

1. Agent-prompt v13 수정 (`scripts/agent-prompt.md`) — 1회 편집
2. 커밋 + push
3. 오전 trigger 수동 실행 → Monitor → 결과 검증
4. 오후 trigger 수동 실행 → Monitor → 결과 검증
5. 사용자 피드백 수집 → 필요 시 v14 로 정교화

단 구현·실행·검증 사이클.
