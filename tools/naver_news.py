"""네이버 뉴스 검색 API 클라이언트 — 시장 동향 브리핑용 뉴스 수집."""
import html
import os
import re
from urllib.parse import urlparse

import requests

NAVER_NEWS_URL = "https://openapi.naver.com/v1/search/news.json"

# 가격 변동 요인 브리핑용 기본 검색어.
# 구조적 일반론보다 하루 단위로 변하는 비용·정책·수급 신호를 우선 수집한다.
DEFAULT_QUERIES = [
    "토마토 도매가격 급등",
    "토마토 출하량 가격",
    "최저임금 인상 농가",
    "농업 인건비 상승",
    "국제유가 상승 농업",
    "면세유 가격 농가",
    "원달러 환율 상승 농산물",
    "환율 상승 수입 농산물",
    "농사용 전기요금 인상",
    "비료 가격 상승",
    "농자재 가격 급등",
    "물류비 상승 농산물",
    "폭염 호우 농산물 가격",
]

_IMPACT_KEYWORDS = (
    "급등", "급락", "상승", "하락", "인상", "인하", "역대", "최고", "최저",
    "환율", "원달러", "유가", "면세유", "전기요금", "최저임금", "인건비",
    "비료", "농자재", "물류비", "출하량", "수입", "수출", "폭염", "호우",
    "한파", "장마", "가뭄", "병해", "가격",
)

_TAG_RE = re.compile(r"<.*?>")


def _clean_text(raw: str) -> str:
    """네이버 API 응답의 HTML 태그(<b> 등)와 엔티티를 제거."""
    return html.unescape(_TAG_RE.sub("", raw)).strip()


def _media_from_link(link: str) -> str:
    """기사 링크 도메인에서 매체명을 근사 추출 (Naver API가 매체명을 별도 제공하지 않음)."""
    host = urlparse(link).netloc
    return host.removeprefix("www.") if host else "출처 미상"


def _impact_score(article: dict) -> int:
    text = f"{article.get('title', '')} {article.get('description', '')}"
    return sum(1 for kw in _IMPACT_KEYWORDS if kw in text)


def search_news(
    query: str,
    client_id: str,
    client_secret: str,
    display: int = 10,
    sort: str = "date",
) -> list[dict]:
    """네이버 뉴스 검색 API 호출 → 정제된 기사 목록 반환.

    Raises:
        requests.HTTPError: API 호출 실패 시 (키 미설정/만료 포함).
    """
    headers = {
        "X-Naver-Client-Id": client_id,
        "X-Naver-Client-Secret": client_secret,
    }
    params = {"query": query, "display": display, "sort": sort}
    resp = requests.get(NAVER_NEWS_URL, headers=headers, params=params, timeout=10)
    resp.raise_for_status()

    articles = []
    for item in resp.json().get("items", []):
        link = item.get("originallink") or item.get("link", "")
        articles.append({
            "title": _clean_text(item.get("title", "")),
            "description": _clean_text(item.get("description", "")),
            "link": link,
            "media": _media_from_link(link),
            "pub_date": item.get("pubDate", ""),
            "query": query,
        })
    return articles


def fetch_price_factor_articles(
    client_id: str,
    client_secret: str,
    queries: list[str] | None = None,
    per_query_count: int = 5,
) -> list[dict]:
    """가격 변동 요인 관련 여러 검색어로 뉴스를 수집하고 링크 기준 중복 제거."""
    queries = queries or DEFAULT_QUERIES
    seen_links: set[str] = set()
    articles = []
    for q in queries:
        for a in search_news(q, client_id, client_secret, display=per_query_count):
            if a["link"] and a["link"] not in seen_links:
                seen_links.add(a["link"])
                articles.append(a)
    return sorted(articles, key=_impact_score, reverse=True)


if __name__ == "__main__":
    _id = os.getenv("NAVER_CLIENT_ID")
    _secret = os.getenv("NAVER_CLIENT_SECRET")
    if not _id or not _secret:
        print("NAVER_CLIENT_ID / NAVER_CLIENT_SECRET 환경변수가 필요합니다.")
    else:
        for _a in fetch_price_factor_articles(_id, _secret, per_query_count=3):
            print(f"[{_a['media']}] {_a['title']} ({_a['pub_date']})")
