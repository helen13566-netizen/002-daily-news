# 데일리 뉴스 브리핑 구현 계획

Seed: `/home/helen/Spec/002-데일리뉴스/seed.yaml` (seed_a66c5613ff40, v1.0.0)
Design: `/home/helen/Spec/002-데일리뉴스/design-preview.html` (FX는 D+E 조합 확정)

## 아키텍처 결정

| 결정 | 내용 |
|------|------|
| AI 모델 | Claude Code Remote Agent(= Claude Opus 4.7) 자체가 LLM 역할 → Anthropic API 키 불필요 |
| 결정론적 처리 | Python 스크립트로 RSS 수집·필터·렌더링·상태관리·git 커밋 수행 |
| 배포 | GitHub Pages — `docs/index.html` 경로, main 브랜치 |
| 알림 | 카카오톡 PlayMCP MemoChat MCP, Agent가 직접 호출 |
| 스케줄 | `/schedule` 스킬로 원격 트리거 2개 (07:00 / 18:00 KST) |
| 상태 영속화 | `state/state.json` git 커밋 |

## 고정 설정

### RSS 피드 6종
- AI: AI타임스, ZDNet Korea, 전자신문
- 종합: 연합뉴스, 매일경제, 한겨레

### 디자인 팔레트
- 배경 `#0D0D0D` / 서페이스 `#161616` `#1C1C1C` / 본문 `#F5F5F5` / 포인트 `#FFA500`
- 제목 Noto Serif KR 700-900 / 본문 Pretendard Variable
- 최대 너비 720px, 모바일 480px breakpoint
- FX: D(섹션 줌인/카드 slide-in/순차 fade-up/지그재그 미세 회전) + E(호버 엠버 invert) 조합

### AI 키워드 6개 (ai_news 분류 기준)
GPT / LLM / 생성형 AI / 딥러닝 / 머신러닝 / Claude 계열
(구현 시 `pipeline/config.py`에서 정확한 목록 결정)

### 인생중요뉴스 스코어링 5가지 상황
경제/생계 · 안전/건강 · 정책/법제 · 기술/일자리 · 국제정세
→ 0-10점 중 8점 이상 `is_must_know=true`

## 태스크 의존성

```
1. 저장소/스켈레톤
   ├─ 2. RSS 수집(collect.py)
   ├─ 3. HTML 렌더러(render.py + template)
   └─ 4. 상태/알림(state.py + notify.py)
        └─ 5. Orchestrator(run.py)
             └─ 6. Agent 절차서
                  └─ 7. Pages + E2E
                       └─ 8. /schedule 트리거 등록
```

## 실행 플로우 (Remote Agent 관점)

```
1. git pull
2. python -m pipeline.run collect                  → state/candidates.json
3. (Agent) candidates.json 읽어 grounded 분석      → state/analyzed.json
4. python -m pipeline.run render                   → docs/index.html, archive/
5. python -m pipeline.run notify-success           → 성공 메시지 텍스트
6. git add . && git commit && git push
7. MCP로 카카오톡 성공 메시지 전송
```

실패 시: 각 단계 3회 재시도 → 실패 → `notify-failure` → MCP 실패 메시지

## 검증 기준 (Seed acceptance_criteria 요약)

- RSS 6개 수집 · AI 키워드 필터 · 중복 제거
- 인생중요뉴스 8점 이상 선별 · grounded(환각 없음)
- 기사 카드 전체 필드(제목·출처·시간·점수·태그·추출이유·AI요약·원문URL)
- 히어로 헤더 · 꼭알아야할뉴스 엠버블록 · 섹션 서페이스박스 · D+E FX
- 푸터: 생성시각·RSS 출처 6개·AI 고지문·ISSUE 번호
- 카카오톡 성공/실패 템플릿 정확 일치
- 실패 시 이전 HTML 보존
- 색상 대비 `#F5F5F5 on #0D0D0D` ≥ 15:1
- 모바일 480px 반응형
