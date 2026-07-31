"""
trend/discovery.py — Multi-source trend discovery
Sources: Google Trends, Reddit, HackerNews, RSS feeds,
         YouTube Trending, GitHub Trending, GNews API
"""
import os, re, time, json, hashlib
from datetime import datetime, timedelta
from typing import List, Dict, Optional
from dataclasses import dataclass, field, asdict
import requests
import feedparser
from loguru import logger
from dotenv import load_dotenv

load_dotenv()


# ──────────────────────────────────────────────
# DATA CLASS
# ──────────────────────────────────────────────

@dataclass
class TrendItem:
    title: str
    source: str
    score: float = 0.0         # raw engagement metric (upvotes / points / volume)
    url: str = ""
    category: str = ""
    published_at: Optional[datetime] = None
    keywords: List[str] = field(default_factory=list)
    extra: Dict = field(default_factory=dict)

    @property
    def slug(self) -> str:
        """Normalised key for deduplication."""
        s = re.sub(r"[^a-z0-9 ]", "", self.title.lower())
        s = re.sub(r"\s+", "-", s.strip())[:200]
        return s

    def to_dict(self) -> dict:
        d = asdict(self)
        d["slug"] = self.slug
        if self.published_at:
            d["published_at"] = self.published_at.isoformat()
        return d


# ──────────────────────────────────────────────
# BASE COLLECTOR
# ──────────────────────────────────────────────

class BaseTrendCollector:
    name = "base"
    rate_limit_delay = 1.0   # seconds between requests

    def collect(self) -> List[TrendItem]:
        raise NotImplementedError

    def _get(self, url: str, params: dict = None, headers: dict = None,
             timeout: int = 10) -> Optional[requests.Response]:
        try:
            resp = requests.get(url, params=params, headers=headers,
                                timeout=timeout)
            resp.raise_for_status()
            time.sleep(self.rate_limit_delay)
            return resp
        except Exception as e:
            logger.warning(f"[{self.name}] HTTP error: {e}")

            if hasattr(e, "response") and e.response is not None:
                print("\nSTATUS:", e.response.status_code)
                print("\nBODY:")
                print(e.response.text)

            return None


# ──────────────────────────────────────────────
# 1. GOOGLE TRENDS  (pytrends, unofficial API)
# Rate limit: ~5 req/min before soft-ban, use sparingly
# ──────────────────────────────────────────────

class GoogleTrendsCollector(BaseTrendCollector):
    name = "google_trends"
    rate_limit_delay = 3.0

    def __init__(self):
        self.geo = os.getenv("GTRENDS_GEO", "US")
        self.timeframe = os.getenv("GTRENDS_TIMEFRAME", "now 1-d")

    def collect(self) -> List[TrendItem]:
        try:
            from pytrends.request import TrendReq
            pt = TrendReq(hl="en-US", tz=360, timeout=(10, 25))
            df = pt.trending_searches(pn="US")   # returns DataFrame
            items = []

            for i, title in enumerate(today):
                items.append(
                    TrendItem(
                        title=str(title),
                        source=self.name,
                        score=float(100 - i),
                        published_at=datetime.utcnow(),
                        keywords=[str(title).lower()]
                    )
                )
            logger.info(f"[google_trends] Collected {len(items)} trends")
            return items[:20]
        except Exception as e:
            logger.error(f"[google_trends] Failed: {e}")
            return []


# ──────────────────────────────────────────────
# 2. REDDIT  (PRAW, OAuth app required, free)
# Rate limit: 60 req/min (OAuth), 10 req/min (anon)
# ──────────────────────────────────────────────

class RedditCollector(BaseTrendCollector):
    name = "reddit"
    rate_limit_delay = 0.5

    def __init__(self):
        import praw
        self.reddit = praw.Reddit(
            client_id=os.getenv("REDDIT_CLIENT_ID", ""),
            client_secret=os.getenv("REDDIT_CLIENT_SECRET", ""),
            user_agent=os.getenv("REDDIT_USER_AGENT", "YTShortsBot/1.0"),
        )
        subs = os.getenv("REDDIT_SUBREDDITS",
            "technology,science,worldnews,todayilearned")
        self.subreddits = [s.strip() for s in subs.split(",")]

    def collect(self) -> List[TrendItem]:
        items = []
        for sub in self.subreddits:
            try:
                subreddit = self.reddit.subreddit(sub)
                for post in subreddit.hot(limit=5):
                    if post.score < 500:
                        continue
                    items.append(TrendItem(
                        title=post.title,
                        source=f"{self.name}/{sub}",
                        score=float(post.score),
                        url=f"https://reddit.com{post.permalink}",
                        category=sub,
                        published_at=datetime.fromtimestamp(post.created_utc),
                        keywords=self._extract_keywords(post.title),
                        extra={"upvote_ratio": post.upvote_ratio,
                               "num_comments": post.num_comments},
                    ))
            except Exception as e:
                logger.warning(f"[reddit/{sub}] Error: {e}")
        logger.info(f"[reddit] Collected {len(items)} posts")
        return items

    def _extract_keywords(self, text: str) -> List[str]:
        stop = {"the","a","an","is","in","on","at","to","of","and","or",
                "for","with","this","that","it","was","as","from"}
        words = re.findall(r"\b[a-zA-Z]{4,}\b", text.lower())
        return [w for w in words if w not in stop][:8]


# ──────────────────────────────────────────────
# 3. HACKER NEWS  (official free API, no key)
# Rate limit: 10,000 req/day, very generous
# ──────────────────────────────────────────────

class HackerNewsCollector(BaseTrendCollector):
    name = "hacker_news"
    BASE = "https://hacker-news.firebaseio.com/v0"
    rate_limit_delay = 0.2

    def collect(self) -> List[TrendItem]:
        resp = self._get(f"{self.BASE}/topstories.json")
        if not resp:
            return []
        ids = resp.json()[:30]
        items = []
        for story_id in ids:
            r = self._get(f"{self.BASE}/item/{story_id}.json")
            if not r:
                continue
            d = r.json()
            if not d or d.get("type") != "story":
                continue
            items.append(TrendItem(
                title=d.get("title", ""),
                source=self.name,
                score=float(d.get("score", 0)),
                url=d.get("url", f"https://news.ycombinator.com/item?id={story_id}"),
                published_at=datetime.fromtimestamp(d.get("time", 0)),
                extra={"comments": d.get("descendants", 0)},
            ))
        logger.info(f"[hacker_news] Collected {len(items)} stories")
        return items


# ──────────────────────────────────────────────
# 4. RSS FEEDS (no key, completely free)
# ──────────────────────────────────────────────

RSS_FEEDS = {
    "bbc_world":       "http://feeds.bbci.co.uk/news/world/rss.xml",
    "techcrunch":      "https://techcrunch.com/feed/",
    "mit_tech_review": "https://www.technologyreview.com/topnews.rss",
    "science_daily":   "https://www.sciencedaily.com/rss/top.xml",
    "guardian_tech":   "https://www.theguardian.com/technology/rss",
    "ars_technica":    "http://feeds.arstechnica.com/arstechnica/index",
    "wired":           "https://www.wired.com/feed/rss",
}

class RSSCollector(BaseTrendCollector):
    name = "rss"
    rate_limit_delay = 0.5

    def __init__(self, feeds: Dict[str, str] = None):
        self.feeds = feeds or RSS_FEEDS

    def collect(self) -> List[TrendItem]:
        items = []
        cutoff = datetime.utcnow() - timedelta(hours=24)
        for feed_name, url in self.feeds.items():
            try:
                feed = feedparser.parse(url)
                for entry in feed.entries[:5]:
                    pub = self._parse_date(entry)
                    if pub and pub < cutoff:
                        continue
                    items.append(TrendItem(
                        title=entry.get("title", ""),
                        source=f"{self.name}/{feed_name}",
                        score=50.0,
                        url=entry.get("link", ""),
                        published_at=pub or datetime.utcnow(),
                    ))
            except Exception as e:
                logger.warning(f"[rss/{feed_name}] Error: {e}")
        logger.info(f"[rss] Collected {len(items)} articles")
        return items

    def _parse_date(self, entry) -> Optional[datetime]:
        for attr in ("published_parsed", "updated_parsed"):
            t = entry.get(attr)
            if t:
                try:
                    return datetime(*t[:6])
                except Exception:
                    pass
        return None


# ──────────────────────────────────────────────
# 5. YOUTUBE TRENDING (YouTube Data API v3, free quota)
# Rate limit: 10,000 units/day free; videsList costs 1 unit
# ──────────────────────────────────────────────

class YouTubeTrendingCollector(BaseTrendCollector):
    name = "youtube_trending"
    BASE = "https://www.googleapis.com/youtube/v3"
    rate_limit_delay = 0.5

    def __init__(self):
        # YouTube API key can be created free at console.cloud.google.com
        self.api_key = os.getenv("YOUTUBE_API_KEY", "")

    def collect(self) -> List[TrendItem]:
        if not self.api_key:
            logger.warning("[youtube_trending] No API key — skipping")
            return []
        resp = self._get(
            f"{self.BASE}/videos",
            params={
                "part": "snippet,statistics",
                "chart": "mostPopular",
                "regionCode": "US",
                "maxResults": 20,
                "key": self.api_key,
            }
        )
        if not resp:
            return []
        items = []
        for item in resp.json().get("items", []):
            s = item["snippet"]
            st = item.get("statistics", {})
            views = int(st.get("viewCount", 0))
            items.append(TrendItem(
                title=s["title"],
                source=self.name,
                score=min(float(views) / 10000, 100.0),
                url=f"https://youtu.be/{item['id']}",
                category=s.get("categoryId", ""),
                published_at=datetime.fromisoformat(
                    s["publishedAt"].replace("Z", "+00:00")),
                extra={"views": views,
                       "likes": int(st.get("likeCount", 0))},
            ))
        logger.info(f"[youtube_trending] Collected {len(items)} videos")
        return items


# ──────────────────────────────────────────────
# 6. GITHUB TRENDING (scraped — no API key)
# ──────────────────────────────────────────────

class GitHubTrendingCollector(BaseTrendCollector):
    name = "github_trending"
    rate_limit_delay = 2.0

    def collect(self) -> List[TrendItem]:

        resp = self._get(
            "https://api.github.com/search/repositories",
            params={
                "q": "created:>2026-06-01",
                "sort": "stars",
                "order": "desc",
                "per_page": 15
            }
        )

        if not resp:
            return []

        items = []

        for repo in resp.json().get("items", []):

            title = f"{repo['full_name']}: {repo.get('description','')}"

            items.append(
                TrendItem(
                    title=title[:200],
                    source=self.name,
                    score=float(repo["stargazers_count"]),
                    url=repo["html_url"],
                    category="technology",
                    published_at=datetime.utcnow(),
                )
            )

        logger.info(
            f"[github_trending] Collected {len(items)} repos"
        )

        return items


# ──────────────────────────────────────────────
# 7. GNEWS API (free: 100 req/day)
# ──────────────────────────────────────────────

class GNewsCollector(BaseTrendCollector):
    name = "gnews"
    BASE = "https://gnews.io/api/v4"
    rate_limit_delay = 1.0

    def __init__(self):
        self.api_key = os.getenv("GNEWS_API_KEY", "")

    def collect(self) -> List[TrendItem]:
        if not self.api_key:
            logger.warning("[gnews] No API key — skipping")
            return []
        resp = self._get(
            f"{self.BASE}/top-headlines",
            params={
                "token": self.api_key,
                "lang": "en",
                "country": "us",
                "max": 10,
            }
        )
        if not resp:
            return []
        items = []
        for art in resp.json().get("articles", []):
            items.append(TrendItem(
                title=art["title"],
                source=self.name,
                score=60.0,
                url=art.get("url", ""),
                published_at=datetime.fromisoformat(
                    art["publishedAt"].replace("Z", "+00:00"))
                    if art.get("publishedAt") else datetime.utcnow(),
            ))
        logger.info(f"[gnews] Collected {len(items)} articles")
        return items


# ──────────────────────────────────────────────
# AGGREGATOR
# ──────────────────────────────────────────────

class TrendAggregator:
    """
    Run all collectors, merge results, remove duplicates.
    """
    def __init__(self):
        self.collectors = [
            HackerNewsCollector(),
            RSSCollector(),
            YouTubeTrendingCollector(),
            GitHubTrendingCollector(),
            GNewsCollector(),
        ]

    def collect_all(self) -> List[TrendItem]:
        all_items: List[TrendItem] = []
        for collector in self.collectors:
            try:
                items = collector.collect()
                all_items.extend(items)
            except Exception as e:
                logger.error(f"Collector {collector.name} crashed: {e}")

        logger.info(f"[aggregator] Total raw items: {len(all_items)}")
        deduped = self._deduplicate(all_items)
        logger.info(f"[aggregator] After dedup: {len(deduped)}")
        return deduped

    def _deduplicate(self, items: List[TrendItem]) -> List[TrendItem]:
        seen_slugs: set = set()
        unique = []
        for item in items:
            if not item.title.strip():
                continue
            slug = item.slug
            if slug not in seen_slugs:
                seen_slugs.add(slug)
                unique.append(item)
        return unique


if __name__ == "__main__":
    agg = TrendAggregator()
    results = agg.collect_all()
    for r in results[:10]:
        print(f"[{r.source}] {r.title[:80]} (score={r.score:.0f})")
