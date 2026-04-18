# 데일리 뉴스 브리핑

매일 오전 7시 · 오후 6시(KST) RSS 뉴스 6개 소스(AI 3 + 종합 3) 수집 → Claude Opus 4.7 grounded 분석 → 다크+엠버 미니멀 HTML 리포트 → GitHub Pages 배포 → 카카오톡 메모채팅 알림.

## 아키텍처

| 계층 | 담당 |
|------|------|
| Python (`pipeline/`) | 결정론적 처리 — RSS 수집, 중복 제거, 키워드 필터, HTML 렌더링, 상태 관리, git 커밋 |
| Claude Code Remote Agent | grounded AI 분석 — 요약, 추출이유, 스코어링, 트렌드 해시태그 |
| PlayMCP (카카오톡 MemoChat) | 성공/실패 알림 전송 |
| GitHub Pages | 최신 리포트 공개 (`docs/index.html`) |

## 디렉토리

```
pipeline/   collect.py render.py notify.py state.py run.py
templates/  report.html.j2
docs/       index.html  (GitHub Pages 배포 대상)
state/      state.json candidates.json analyzed.json
archive/    YYYY-MM-DD-HHMM.html
scripts/    agent-prompt.md  (Remote Agent 실행 절차서)
tests/      pytest 단위 테스트
```

## 실행 방식

1. `/schedule` 스킬로 매일 07:00 / 18:00 KST 원격 트리거 2개 등록
2. 트리거 발화 시 Remote Agent가 `scripts/agent-prompt.md` 절차 수행
3. Python 파이프라인으로 수집·렌더링·배포, Agent가 직접 grounded 분석 · MCP 알림

## 상태 관리

`state/state.json`에 pipeline_status, failed_stage, retry_count, issue_number, last_success_at, next_run_time, deploy_url를 기록하고 git 커밋으로 영속화.

## 실패 처리

단계 실패 시 최대 3회 재시도, 모두 실패하면 이전 `docs/index.html`을 보존하고 카카오톡으로 실패 알림만 전송.
