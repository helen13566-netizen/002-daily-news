# 뉴스 인사이트 레이어 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 각 기사 카드의 `.why` 박스를 클릭하면 AI 시니어 편집장 관점의 인사이트 2~4축이 펼쳐지는 토글 레이어 추가.

**Architecture:** (1) Jinja2 템플릿에서 `article.insights` 유무로 `<details>` 분기. (2) agent-prompt v9 에 시니어 편집장 페르소나·문체·축 선택 가이드 주입. (3) render 는 스키마 통과만 담당. (4) insights 없을 때 기존 `.why` 박스 폴백으로 하위호환.

**Tech Stack:** Python 3.12, Jinja2, 기존 `pipeline/*`, pytest, HTML `<details>/<summary>` 표준(JS 없음).

**Spec:** `docs/superpowers/specs/2026-04-19-news-insight-layer-design.md`

---

## File Structure

| 파일 | 역할 | 변경 유형 |
|------|------|----------|
| `templates/report.html.j2` | 카드 UI — `<details>` 분기 + 신규 CSS | Modify |
| `tests/test_render.py` | 인사이트 유/무/bonus 렌더 테스트 3건 | Modify |
| `scripts/agent-prompt.md` | v9: 단계 D 아래 인사이트 서브섹션 신설 | Modify |
| `pipeline/render.py` | 변경 없음 (analyzed dict 를 그대로 템플릿에 전달) | Verify only |

---

## Task 1: 인사이트 렌더링 (TDD)

**Files:**
- Test: `tests/test_render.py`
- Modify: `templates/report.html.j2`
- Verify: `pipeline/render.py` (변경 없음)

- [ ] **Step 1: 실패 테스트 작성 — insights 포함 렌더**

파일 `tests/test_render.py` 하단에 추가:

```python
def test_insights_block_rendered_when_present(tmp_path: Path) -> None:
    """insights 필드가 있으면 details 토글 블록이 렌더된다."""
    import json
    from pipeline import render as render_mod
    analyzed = {
        "issue_number": 1,
        "generation_timestamp": "2026-04-19T07:00:00+09:00",
        "trend_hashtags": ["AI"],
        "articles": [{
            "article_id": "a1",
            "title": "샘플 기사",
            "source": "테스트",
            "published_at": "2026-04-19T06:00:00+09:00",
            "original_url": "https://example.com/a1",
            "content_text": "본문",
            "category": "ai_news",
            "keywords": ["AI"],
            "ai_summary": "요약입니다.",
            "extraction_reason": "주목해야 할 이유",
            "relevance_score": 9.0,
            "is_must_know": True,
            "insights": {
                "ripple": {
                    "title": "이게 우리한테 어떻게 영향을 줄까?",
                    "icon": "📡",
                    "text": "파급 효과 설명 문단입니다.",
                },
                "history": {
                    "title": "예전에도 이런 일이 있었을까?",
                    "icon": "🗂",
                    "text": "역사 비교 설명 문단입니다.",
                },
                "bonus": [],
            },
        }],
    }
    path = tmp_path / "analyzed.json"
    path.write_text(json.dumps(analyzed, ensure_ascii=False), encoding="utf-8")
    out_path = tmp_path / "index.html"
    archive_dir = tmp_path / "archive"
    archive_dir.mkdir()
    render_mod.render(
        analyzed_path=str(path),
        output_path=str(out_path),
        archive_dir=str(archive_dir),
    )
    html = out_path.read_text(encoding="utf-8")
    assert '<details class="why-insights"' in html
    assert "이게 우리한테 어떻게 영향을 줄까?" in html
    assert "예전에도 이런 일이 있었을까?" in html
    assert "파급 효과 설명 문단입니다." in html
    assert "역사 비교 설명 문단입니다." in html
```

- [ ] **Step 2: 테스트 실행 — 실패 확인**

Run: `python3 -m pytest tests/test_render.py::test_insights_block_rendered_when_present -v`

Expected: FAIL (assert `'<details class="why-insights"' in html` — 현재 템플릿에 `<details>` 없음)

- [ ] **Step 3: 템플릿에 `<details>` 분기 추가**

`templates/report.html.j2` 에서 기존 `.why` 블록을 찾기 (Grep 으로 `<div class="why">` 검색) 해서 다음으로 교체:

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

- [ ] **Step 4: CSS 추가**

`templates/report.html.j2` 의 `<style>` 블록 내 기존 `.article .why` 규칙 바로 다음 위치에 다음 블록 추가:

```css
    /* 인사이트 토글 — <details> 기반, JS 없음 */
    .why-insights {
      background: var(--accent-soft);
      border-left: 2px solid var(--accent);
      border-radius: 0 3px 3px 0;
      padding: 9px 13px;
      margin-bottom: 14px;
      font-size: 13px;
      color: var(--text-sub);
    }
    .why-insights > summary.why {
      background: transparent;
      border-left: 0;
      padding: 0;
      margin-bottom: 0;
      cursor: pointer;
      list-style: none;
    }
    .why-insights > summary.why::-webkit-details-marker { display: none; }
    .why-insights > summary.why::marker { content: ""; }
    .why-insights .expand-hint {
      margin-left: 8px;
      color: var(--accent);
      transition: transform 0.2s;
      display: inline-block;
    }
    .why-insights[open] > summary.why .expand-hint { transform: rotate(180deg); }
    .why-insights .insights-body {
      margin-top: 10px;
      padding-top: 10px;
      border-top: 1px dashed var(--border);
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
      margin: 0;
    }
```

- [ ] **Step 5: 테스트 재실행 — 통과 확인**

Run: `python3 -m pytest tests/test_render.py::test_insights_block_rendered_when_present -v`

Expected: PASS

- [ ] **Step 6: 하위호환 테스트 추가**

`tests/test_render.py` 에 이어서 추가:

```python
def test_insights_absent_falls_back_to_simple_why(tmp_path: Path) -> None:
    """insights 필드가 없으면 기존 .why 박스만 렌더 (하위호환)."""
    import json
    from pipeline import render as render_mod
    analyzed = {
        "issue_number": 1,
        "generation_timestamp": "2026-04-19T07:00:00+09:00",
        "trend_hashtags": [],
        "articles": [{
            "article_id": "a1",
            "title": "샘플",
            "source": "테스트",
            "published_at": "2026-04-19T06:00:00+09:00",
            "original_url": "https://example.com/a1",
            "content_text": "본문",
            "category": "ai_news",
            "keywords": [],
            "ai_summary": "요약",
            "extraction_reason": "이유",
            "relevance_score": 5.0,
            "is_must_know": False,
            # insights 필드 의도적으로 없음
        }],
    }
    path = tmp_path / "analyzed.json"
    path.write_text(json.dumps(analyzed, ensure_ascii=False), encoding="utf-8")
    out_path = tmp_path / "index.html"
    archive_dir = tmp_path / "archive"
    archive_dir.mkdir()
    render_mod.render(
        analyzed_path=str(path),
        output_path=str(out_path),
        archive_dir=str(archive_dir),
    )
    html = out_path.read_text(encoding="utf-8")
    assert '<details class="why-insights"' not in html
    assert "추출이유</strong> 이유" in html
```

- [ ] **Step 7: 테스트 실행 — 통과**

Run: `python3 -m pytest tests/test_render.py::test_insights_absent_falls_back_to_simple_why -v`

Expected: PASS (템플릿의 `{% if %}` 분기에서 else 로 가 폴백)

- [ ] **Step 8: 보너스 축 테스트 추가**

`tests/test_render.py` 에 이어서 추가:

```python
def test_insights_bonus_axes_rendered(tmp_path: Path) -> None:
    """insights.bonus 리스트의 각 항목이 독립 블록으로 렌더된다."""
    import json
    from pipeline import render as render_mod
    analyzed = {
        "issue_number": 1,
        "generation_timestamp": "2026-04-19T07:00:00+09:00",
        "trend_hashtags": [],
        "articles": [{
            "article_id": "a1",
            "title": "샘플",
            "source": "테스트",
            "published_at": "2026-04-19T06:00:00+09:00",
            "original_url": "https://example.com/a1",
            "content_text": "본문",
            "category": "ai_news",
            "keywords": [],
            "ai_summary": "요약",
            "extraction_reason": "이유",
            "relevance_score": 9.0,
            "is_must_know": True,
            "insights": {
                "ripple": {"title": "RT", "icon": "📡", "text": "R text"},
                "history": {"title": "HT", "icon": "🗂", "text": "H text"},
                "bonus": [
                    {"type": "personal", "title": "나는 뭘 해야 할까?", "icon": "💡", "text": "P text"},
                    {"type": "scenario", "title": "앞으로 어떻게 될까?", "icon": "🔮", "text": "S text"},
                ],
            },
        }],
    }
    path = tmp_path / "analyzed.json"
    path.write_text(json.dumps(analyzed, ensure_ascii=False), encoding="utf-8")
    out_path = tmp_path / "index.html"
    archive_dir = tmp_path / "archive"
    archive_dir.mkdir()
    render_mod.render(
        analyzed_path=str(path),
        output_path=str(out_path),
        archive_dir=str(archive_dir),
    )
    html = out_path.read_text(encoding="utf-8")
    assert "나는 뭘 해야 할까?" in html
    assert "P text" in html
    assert "앞으로 어떻게 될까?" in html
    assert "S text" in html
    assert 'data-axis="personal"' in html
    assert 'data-axis="scenario"' in html
```

- [ ] **Step 9: 테스트 실행 — 통과**

Run: `python3 -m pytest tests/test_render.py::test_insights_bonus_axes_rendered -v`

Expected: PASS

- [ ] **Step 10: 전체 regression 확인**

Run: `python3 -m pytest tests/ -q`

Expected: 모든 테스트 PASS (기존 56 + 신규 3 = 59)

- [ ] **Step 11: 커밋**

```bash
git add tests/test_render.py templates/report.html.j2
git -c user.email=helen1356@naver.com -c user.name=helen13566-netizen commit -m "feat(insights): <details> 토글로 인사이트 레이어 렌더

- .why 박스를 article.insights 존재 시 <details>로 래핑
- ripple/history 고정 2축 + bonus 배열 렌더
- insights 없을 시 기존 .why 박스 폴백 (하위호환)
- CSS: 엠버 경계 유지, 펼침 화살표 회전 애니메이션, JS 불필요
- tests/test_render.py: 3개 신규 테스트 (insights 유/무/bonus)

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: Agent Prompt v9 업데이트

**Files:**
- Modify: `scripts/agent-prompt.md`

- [ ] **Step 1: 단계 D 아래 "인사이트 레이어" 서브섹션 추가**

`scripts/agent-prompt.md` 에서 `#### ⚡ 효율 수칙 (시간 예산 엄수, v8)` 섹션 끝부분 (6번 항목 이후) 와 `#### 🔒 절대 제약` 섹션 사이에 다음 블록 삽입:

```markdown
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
- **`ripple`** (파급효과): 이 사건이 다른 산업·국가·계층에 어떻게 연쇄적으로 퍼지는지
  - 헤딩: `📡 이게 우리한테 어떻게 영향을 줄까?`
- **`history`** (역사·비교): 유사한 과거 사례·다른 나라 사례와 비교
  - 헤딩: `🗂 예전에도 이런 일이 있었을까?`

##### 보너스 축 (AI 판단으로 추가 또는 교체)

| type | 헤딩 | 아이콘 |
|------|------|--------|
| `personal` | 나는 뭘 해야 할까? | 💡 |
| `scenario` | 앞으로 어떻게 될 수 있을까? | 🔮 |
| `frame` | 이 뉴스, 이렇게 읽어보세요 | 🧐 |
| `perspective` | 입장이 다르면 어떻게 보일까? | 👥 |

##### 축 선택 가이드

| 기사 유형 | 구성 |
|-----------|------|
| 국제·외교·분쟁 | 기본 C+D + `scenario` |
| 통화·금리·부동산 | 기본 C+D + `personal` |
| 기업 M&A·사업 구조 | 기본 C+D + `perspective` +`scenario` |
| AI·기술 신제품 | 기본 C+D + `personal` |
| 재난·안전·의료 | 기본 C+D + `personal` |
| 정치 논란·숫자 출처 모호 | `history` 유지 + **`ripple` 교체 → `frame`** |
| 연예·스포츠·단순 속보 | insights 생략 가능 (score ≤ 4, must_know 아님) |

한 기사당 최종 축 수: **2~4개**.

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

##### 시간 예산 (v8 효율 수칙 연장)
- 한 기사당 insights 전체가 800자 이내.
- 단일 Python 블록에서 모든 기사에 대해 한 번에 dict 구성 후 JSON write.
- 시간이 정말 촉박하면 insights 생략 가능 (render 가 자동 폴백). 단 가능하면 `must_know=True` 기사는 필수 포함.
```

- [ ] **Step 2: 커밋**

```bash
git add scripts/agent-prompt.md
git -c user.email=helen1356@naver.com -c user.name=helen13566-netizen commit -m "feat(agent-prompt): v9 인사이트 레이어 지시

시니어 편집장 페르소나, 중학생 어휘 문체 규칙, 기본 2축(ripple/history)
+ 보너스 4축(personal/scenario/frame/perspective), 기사 유형별 축 선택 가이드,
insights 스키마, v8 효율 수칙 연장.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: 로컬 스모크 + Push + Remote Agent 검증

**Files:** 없음 (운영)

- [ ] **Step 1: 샘플 analyzed.json 으로 로컬 render 스모크**

```bash
python3 << 'PY'
import json, pathlib
sample = {
  "issue_number": 99,
  "generation_timestamp": "2026-04-19T07:00:00+09:00",
  "trend_hashtags": ["AI", "금리"],
  "articles": [{
    "article_id": "demo",
    "title": "샘플 기사 — 인사이트 레이어 데모",
    "source": "AI타임스",
    "published_at": "2026-04-19T06:30:00+09:00",
    "original_url": "https://example.com",
    "content_text": "샘플 본문입니다.",
    "category": "ai_news",
    "keywords": ["AI"],
    "ai_summary": "샘플 기사의 요약입니다. 이 기사는 데모용이며 실제 내용은 없습니다.",
    "extraction_reason": "인사이트 레이어 데모용 기사입니다.",
    "relevance_score": 9.0,
    "is_must_know": True,
    "insights": {
      "ripple": {"title": "이게 우리한테 어떻게 영향을 줄까?", "icon": "📡",
       "text": "이 사건이 일어나면 관련 업계부터 영향을 받게 됩니다. 비슷한 일을 하는 회사들의 주가가 먼저 움직이고, 며칠 뒤면 소비자 물가에도 조금씩 반영될 가능성이 있어요."},
      "history": {"title": "예전에도 이런 일이 있었을까?", "icon": "🗂",
       "text": "2020년에 비슷한 상황이 있었습니다. 그때는 한 달 정도 지나서 상황이 정리됐는데, 그 사이 시장이 크게 출렁였어요. 이번에도 비슷한 흐름일 가능성이 높지만, 외부 환경이 달라 더 오래갈 수도 있습니다."},
      "bonus": [
        {"type": "personal", "title": "나는 뭘 해야 할까?", "icon": "💡",
         "text": "당장 큰 결정을 내리기보다, 이번 주 발표되는 후속 자료를 한 번 더 확인해보는 게 좋아요. 특히 투자나 대출을 계획 중이라면 며칠 여유를 두고 판단하는 것을 추천합니다."}
      ]
    }
  }]
}
pathlib.Path("/tmp/insights-demo.json").write_text(json.dumps(sample, ensure_ascii=False, indent=2), encoding="utf-8")
print("샘플 생성: /tmp/insights-demo.json")
PY

mkdir -p /tmp/insights-archive
python3 -c "
from pipeline.render import render
r = render(analyzed_path='/tmp/insights-demo.json',
           output_path='/tmp/insights-demo.html',
           archive_dir='/tmp/insights-archive')
print(r)
"
```

Expected: `{"html_path": "/tmp/insights-demo.html", ..., "article_count": 1}`

- [ ] **Step 2: 생성된 HTML 주요 요소 grep 검증**

```bash
grep -c '<details class="why-insights"' /tmp/insights-demo.html
grep -c 'data-axis="ripple"' /tmp/insights-demo.html
grep -c 'data-axis="history"' /tmp/insights-demo.html
grep -c 'data-axis="personal"' /tmp/insights-demo.html
```

Expected: 각 1

- [ ] **Step 3: Push**

```bash
git push origin main
```

Expected: `main -> main` 정상 push

- [ ] **Step 4: 오전 trigger 수동 실행**

RemoteTrigger 도구 호출:
- action: `run`
- trigger_id: `trig_01T3xa9GjztjfRYgKzfgdZoz`

Expected: HTTP 200

- [ ] **Step 5: Monitor 가동 (새 커밋 감지)**

Monitor 도구 호출:
- description: "v9 인사이트 레이어 검증"
- timeout_ms: 900000
- persistent: false
- command:
```bash
cd /home/helen/Dev/002-데일리뉴스
START_SHA=$(git ls-remote origin main | awk '{print $1}')
echo "[start] baseline=$START_SHA $(date +%H:%M:%S)"
for i in $(seq 1 15); do
  sleep 60
  NEW_SHA=$(git ls-remote origin main | awk '{print $1}')
  if [ "$NEW_SHA" != "$START_SHA" ]; then
    echo "[new-commits] $(date +%H:%M:%S)"
    git fetch origin main -q
    git log --oneline "$START_SHA..$NEW_SHA" | head -10
    exit 0
  fi
  echo "[tick-$i/15] $(date +%H:%M:%S)"
done
exit 1
```

Expected: 4~10분 내 새 커밋 감지 (Actions collect + agent 완료)

- [ ] **Step 6: insights 필드 생성 여부 검증**

```bash
git fetch origin main -q
git show origin/main:state/analyzed.json | python3 -c "
import json, sys
d = json.load(sys.stdin)
arts = d['articles']
with_insights = [a for a in arts if a.get('insights')]
print(f'총 {len(arts)}건 중 insights 포함: {len(with_insights)}건')
for a in with_insights[:3]:
    print(f'- {a[\"title\"][:40]}')
    ins = a['insights']
    print(f'  ripple ({len(ins[\"ripple\"][\"text\"])}자): {ins[\"ripple\"][\"text\"][:50]}...')
    print(f'  history ({len(ins[\"history\"][\"text\"])}자): {ins[\"history\"][\"text\"][:50]}...')
    for b in ins.get('bonus', []):
        print(f'  bonus {b[\"type\"]} ({len(b[\"text\"])}자): {b[\"text\"][:50]}...')
"
```

Expected:
- `must_know=True` 기사 대부분에 insights 포함
- 각 `ripple.text`, `history.text` 길이 120~220자
- bonus 축 0~2개

- [ ] **Step 7: GitHub Pages 브라우저 확인**

https://helen13566-netizen.github.io/002-daily-news/ 열기. 캐시 새로고침(Ctrl+F5).

확인 포인트:
- 카드의 `.why` 박스에 `▾` 화살표
- 클릭 시 insights 블록 펼쳐짐
- 각 축 헤딩(📡/🗂/💡/🔮/🧐/👥) + 서술형 본문
- 다시 클릭 시 접힘
- 중학생 수준 어휘로 작성되었는지 2~3개 샘플 육안 검증

- [ ] **Step 8: 검증 완료 후 종료**

사용자에게 결과 공유:
- insights 생성 성공률
- 카드 토글 UI 동작
- 문체 수준 피드백 요청

---

## Spec Coverage Self-Review

| Spec 섹션 | 커버 Task |
|-----------|----------|
| §3 페르소나 | Task 2 Step 1 (agent-prompt 페르소나 블록) |
| §4 문체 규칙 | Task 2 Step 1 (문체 규칙 블록) |
| §5 인사이트 축 6종 | Task 2 Step 1 (축 정의·선택 가이드) |
| §6 analyzed.json 스키마 | Task 2 Step 1 (스키마 JSON) |
| §7 UI 설계 `<details>` | Task 1 Step 3 (HTML), Task 1 Step 4 (CSS) |
| §7 접근성 (키보드 토글) | `<details>` 자체가 표준 지원 |
| §8 agent prompt 변경 | Task 2 |
| §9 변경 파일 목록 | Task 1 (template, test), Task 2 (agent-prompt). render.py 변경 없음 (verify only). |
| §10 테스트 전략 | Task 1 Steps 1, 6, 8 (3개 테스트), Task 3 Steps 1-2 (로컬 스모크), Task 3 Steps 4-7 (프로덕션) |
| §11 롤백 플랜 | `{% if article.insights %}` 분기로 자연 폴백 (Task 1 Step 3) |
| §12 성공 기준 | Task 3 Step 6 (insights 포함률), Step 7 (육안 검증) |

**Placeholder scan:** 없음. 모든 step 에 실제 코드·명령·expected 포함.

**Type consistency:** `insights.ripple.title/icon/text`, `insights.history.*`, `insights.bonus[].type/title/icon/text` 스키마가 Task 1 (template), Task 2 (agent-prompt), Task 3 (검증 script) 에서 동일.

**Ambiguity:** 없음. 축 type 은 `personal|scenario|frame|perspective` 로 한정.

---

## 이후 단계

Task 1 → Task 2 → Task 3 순서로 실행. Task 1 은 로컬 TDD (커밋 가능), Task 2 는 단순 doc 업데이트, Task 3 은 운영 검증.
