"""고정 설정값 — RSS 피드·키워드·스코어링 기준."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RSSFeed:
    name: str
    url: str
    category: str  # "ai_news" | "general_news"


RSS_FEEDS: tuple[RSSFeed, ...] = (
    RSSFeed("AI타임스", "https://www.aitimes.com/rss/allArticle.xml", "ai_news"),
    RSSFeed("ZDNet Korea", "https://feeds.feedburner.com/zdkorea", "ai_news"),
    RSSFeed("전자신문", "https://rss.etnews.com/Section901.xml", "ai_news"),
    RSSFeed("연합뉴스", "https://www.yna.co.kr/rss/news.xml", "general_news"),
    RSSFeed("매일경제", "https://www.mk.co.kr/rss/30000001/", "general_news"),
    RSSFeed("한겨레", "https://www.hani.co.kr/rss/", "general_news"),
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

DEPLOY_URL: str = "https://helen13566-netizen.github.io/002-daily-news/"

STATE_JSON_PATH: str = "state/state.json"
CANDIDATES_JSON_PATH: str = "state/candidates.json"
ANALYZED_JSON_PATH: str = "state/analyzed.json"
OUTPUT_HTML_PATH: str = "docs/index.html"
ARCHIVE_DIR: str = "archive"
