"""고정 설정값 — RSS 피드·키워드·스코어링 기준."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RSSFeed:
    name: str
    url: str
    category: str  # "ai_news" | "general_news" | "official_ai"
    # tz 없는 pubDate 를 해석할 기본 시간대. 한국 소스는 KST 의미로 주지만
    # feedparser 가 UTC 로 가정해 +9h 미래로 찍히는 버그가 있었음 (v19 수정).
    # 해외 소스는 pubDate 가 tz 명시되거나 UTC 의미가 관행.
    default_tz: str = "Asia/Seoul"
    # None → 기본 오전/오후 고정 윈도우 적용. 정수면 (now - N시간) ~ now rolling
    # 윈도우. 공식 AI 소스처럼 발행 주기가 낮은 피드(주 1~3회)에 72 를 주면
    # 지난 72 시간 안의 발표를 전부 포함해 주기 결핍 완화.
    window_hours: int | None = None


RSS_FEEDS: tuple[RSSFeed, ...] = (
    # 한국 소스 (default_tz=KST 이 기본값)
    RSSFeed("AI타임스", "https://www.aitimes.com/rss/allArticle.xml", "ai_news"),
    RSSFeed("ZDNet Korea", "https://feeds.feedburner.com/zdkorea", "ai_news"),
    RSSFeed("전자신문", "https://rss.etnews.com/Section901.xml", "ai_news"),
    RSSFeed("연합뉴스", "https://www.yna.co.kr/rss/news.xml", "general_news"),
    RSSFeed("매일경제", "https://www.mk.co.kr/rss/30000001/", "general_news"),
    RSSFeed("한겨레", "https://www.hani.co.kr/rss/", "general_news"),
    # 공식 AI 소스 (v20) — category=official_ai · window_hours=72 로 주기 결핍 완화
    RSSFeed(
        "OpenAI Blog", "https://openai.com/blog/rss.xml",
        "official_ai", default_tz="UTC", window_hours=72,
    ),
    RSSFeed(
        "Google DeepMind", "https://deepmind.google/blog/rss.xml",
        "official_ai", default_tz="UTC", window_hours=72,
    ),
    RSSFeed(
        "Simon Willison", "https://simonwillison.net/atom/everything/",
        "official_ai", default_tz="UTC", window_hours=72,
    ),
    RSSFeed(
        "Anthropic SDK Releases",
        "https://github.com/anthropics/anthropic-sdk-python/releases.atom",
        "official_ai", default_tz="UTC", window_hours=72,
    ),
    # 연예 소스 (2026-05) — category=entertainment_news, 한국 KST 기본
    RSSFeed(
        "연합뉴스 연예", "https://www.yna.co.kr/rss/entertainment.xml",
        "entertainment_news",
    ),
    RSSFeed(
        "매일경제 연예", "https://www.mk.co.kr/rss/50400012/",
        "entertainment_news",
    ),
    RSSFeed(
        "한국경제 연예", "https://www.hankyung.com/feed/entertainment",
        "entertainment_news",
    ),
)

# AI 키워드 확장 목록 — 매치 시 해당 기사는 category="ai_news" 로 재분류
# ASCII 키워드는 word boundary 매칭(대소문자 무시), 한글/공백 포함 키워드는 literal.
AI_KEYWORDS: tuple[str, ...] = (
    # 모델·기술
    "GPT",
    "LLM",
    "생성형 AI",
    "딥러닝",
    "머신러닝",
    "트랜스포머",
    "뉴럴",
    # 주요 제품·브랜드
    "Claude",
    "Anthropic",
    "앤트로픽",
    "OpenAI",
    "챗GPT",
    "ChatGPT",
    "Gemini",
    "제미나이",
    "Google",
    "엔비디아",
    # 일반 용어
    "AI",
    "인공지능",
    "챗봇",
    "에이전트",
    "자율주행",
    "로봇",
)

# 인생중요뉴스 스코어링 5가지 상황
LIFE_IMPACT_DIMENSIONS: tuple[str, ...] = (
    "경제/생계",
    "안전/건강",
    "정책/법제",
    "기술/일자리",
    "국제정세",
)

MUST_KNOW_SCORE_THRESHOLD: float = 8.0

MAX_RETRY: int = 3

KST_TZ_NAME: str = "Asia/Seoul"

# 수집 시간 윈도우 경계 — 오전 브리핑(08:25 KST)·오후 브리핑(17:25 KST) 시각과 일치.
# 수집이 이 시각 이전에 실행되어도(브리핑 10분 전 cron) 윈도우 경계는 브리핑 시각을 기준으로 한다.
MORNING_CUTOFF_HOUR: int = 8
MORNING_CUTOFF_MINUTE: int = 25
EVENING_CUTOFF_HOUR: int = 17
EVENING_CUTOFF_MINUTE: int = 25

DEPLOY_URL: str = "https://helen13566-netizen.github.io/002-daily-news/"

STATE_JSON_PATH: str = "state/state.json"
CANDIDATES_JSON_PATH: str = "state/candidates.json"
ANALYZED_JSON_PATH: str = "state/analyzed.json"
OUTPUT_HTML_PATH: str = "docs/index.html"
ARCHIVE_DIR: str = "archive"
