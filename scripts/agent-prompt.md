# Remote Agent 실행 절차서 (v5 · SSH Deploy Key)

## v5 핵심

PAT·MCP push_files 모두 권한 이슈로 막혔다. 대신 **저장소 전용 SSH deploy key** 로 `git push` 한다. trigger prompt 첫머리에서 sandbox 의 `~/.ssh/id_ed25519` 에 개인키가 미리 설치되어 있다.

| 경로 | 상태 |
|------|------|
| PAT 주입 | 폐기 |
| MCP push_files | 폐기 (contents:write 없음) |
| `gh` CLI | 사용 불가 (sandbox 에 없음) |
| **SSH Deploy Key + `git push`** | ✅ v5 |

Deploy key 는 저장소 1개에만 write 권한을 주고 workflow scope 개념이 없다(= workflow 파일이 아닌 변경은 자유롭게 push).

## 환경 확인

- working directory: clone 된 저장소
- `~/.ssh/id_ed25519` 는 trigger prompt 에서 이미 설치됨 (읽기권한 600)
- `git remote get-url origin` → 이미 `git@github.com:helen13566-netizen/002-daily-news.git`
- `TZ=Asia/Seoul` set, `pip install --user --break-system-packages -r requirements.txt` 완료
- git identity `helen1356@naver.com` / `helen13566-netizen`

## 파이프라인

```
Actions collect.yml (cron 06:55/17:55 KST)
  → RSS 6개 수집 → state/candidates.json 커밋
         ↓
Remote agent (cron 07:00/18:00 KST)
  → git pull                     ← candidates.json 수신
  → prepare-run                  ← issue_number 증가, state.json 로컬 수정
  → grounded 분석 → state/analyzed.json
  → render → docs/index.html + archive/YYYY-MM-DD-HHMM.html
  → mark-success → state/state.json 갱신
  → git add + commit + push      ← SSH deploy key 경로
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

`$PERIOD` 는 오전 트리거면 `"오전"`, 오후 트리거면 `"오후"`.

### 단계 C — candidates.json 신선도 검증

```bash
test -s state/candidates.json || { FAILED_STAGE=collecting; ERROR_REASON="candidates.json 없음"; }
AGE_MIN=$(( ($(date +%s) - $(stat -c %Y state/candidates.json)) / 60 ))
if [ "$AGE_MIN" -gt 60 ]; then
  FAILED_STAGE=collecting
  ERROR_REASON="candidates.json 이 ${AGE_MIN}분 전 수집 (Actions cron 누락 의심)"
fi
```

`FAILED_STAGE` set 되면 **단계 X** 로.

### 단계 D — grounded 분석

`state/candidates.json` → `state/analyzed.json` 작성.

#### 🔒 절대 제약
`ai_summary` / `extraction_reason` 은 해당 기사의 `title` + `content_text` 범위 안에서만. 원문에 없는 사실·숫자·인용·해석 금지. 원문 부실 시 기사 제외.

#### 출력 schema

```json
{
  "issue_number": <prepare-run 의 issue_number>,
  "generation_timestamp": <prepare-run 의 generation_timestamp>,
  "trend_hashtags": ["...", ...],
  "articles": [
    {
      "article_id": "...", "title": "...", "source": "...",
      "published_at": "...", "original_url": "...",
      "content_text": "...", "category": "ai_news|general_news",
      "keywords": [...],
      "ai_summary": "<140~220자>",
      "extraction_reason": "<40~80자>",
      "relevance_score": <0-10>,
      "is_must_know": <score >= 8.0>
    }
  ]
}
```

#### 점수 기준 — 5차원 최고값

1. 경제/생계  2. 안전/건강  3. 정책/법제  4. 기술/일자리  5. 국제정세

루머·가십·연예·스포츠 ≤ 4점.

#### 제약
- 최소 3건 (미달 시 `FAILED_STAGE=analyzing`)
- 최대 30건 (초과 시 score 상위 30건)

#### 저장
```bash
python3 - <<'PY'
import json, pathlib
analyzed = { ... 당신이 구성 ... }
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

### 단계 F — git commit + push (핵심)

```bash
git add docs/ archive/ state/state.json state/analyzed.json
git status --short

git commit -m "news: ISSUE #${ISSUE_NUMBER} ${PERIOD} 브리핑 $(date +%Y-%m-%d_%H:%M_KST)"

# 3회 재시도
for attempt in 1 2 3; do
  if git push origin main; then
    echo "✓ push 성공 (attempt $attempt)"
    PUSH_OK=1
    break
  fi
  echo "push 실패 (attempt $attempt)" >&2
  [ "$attempt" = "3" ] && { FAILED_STAGE=deploying; ERROR_REASON="git push 3회 재시도 실패"; }
  sleep $((attempt * 5))
done
```

`FAILED_STAGE=deploying` 되면 단계 X. 성공이면 단계 G.

### 단계 G — 카카오 성공 알림

```bash
python3 -m pipeline.run mark-stage --stage notifying
SUCCESS_MSG=$(python3 -m pipeline.run notify-success)
echo "=== 전송할 메시지 ==="
echo "$SUCCESS_MSG"
```

**PlayMCP 호출**:
```
도구: mcp__claude_ai_PlayMCP__KakaotalkChat-MemoChat
인자: text=<SUCCESS_MSG 전체 원문, 수정·요약 금지>
```

**MCP 응답을 stdout 에 그대로 기록** (수신 검증용).

MCP 실패 시 3회 재시도. 파이프라인 성공 이미 확정이므로 MCP 실패 시에도 종료 상태는 completed, stderr 경고만.

### 단계 H — 종료 보고

```json
{"status": "completed", "issue_number": N, "article_count": N, "failed_stage": null, "kakao_message": "<원문>", "mcp_kakao_response": "<원문>", "duration_seconds": N}
```

---

## 단계 X — 실패 처리

```bash
python3 -m pipeline.run mark-failure --stage "$FAILED_STAGE" --reason "$ERROR_REASON"

# state.json 만 커밋·푸시, docs 는 건드리지 않음
git add state/state.json
git commit -m "state: failure at $FAILED_STAGE (ISSUE #$ISSUE_NUMBER $PERIOD)" || true
git push origin main 2>&1 || echo "state push 실패 (무시)" >&2

FAILURE_MSG=$(python3 -m pipeline.run notify-failure)
echo "$FAILURE_MSG"
```

PlayMCP 로 `FAILURE_MSG` 전송 (3회 재시도). stdout JSON:

```json
{"status": "failed", "failed_stage": "...", "error_reason": "...", "kakao_message": "<원문>", "mcp_kakao_response": "<원문>"}
```

종료 코드 0.

---

## 자기 검증 체크

- [ ] `ssh -T git@github.com` 이 `successfully authenticated` 반환
- [ ] candidates.json 이 60분 이내 수집
- [ ] analyzed.json grounded 준수
- [ ] must_know 기사 score ≥ 8.0
- [ ] trend_hashtags 3~8 개
- [ ] issue_number 일치 (prepare-run/state/analyzed)
- [ ] git push 성공
- [ ] 카카오 MCP 응답 원문 stdout 기록
