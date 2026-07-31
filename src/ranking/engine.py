"""
ranking/engine.py — AI-powered topic scoring and ranking system

Scoring formula:
  final_score = (
      volume_score  * W_VOLUME    +
      recency_score * W_RECENCY   +
      virality_score* W_VIRALITY  +
      (1 - competition_score) * W_COMPETITION
  ) * 100
"""
import os, math, re, json
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass
from loguru import logger
from dotenv import load_dotenv
import random
load_dotenv()

# Weight config (all must sum to 1.0)
W_VOLUME      = float(os.getenv("WEIGHT_SEARCH_VOLUME", 0.30))
W_RECENCY     = float(os.getenv("WEIGHT_RECENCY",       0.25))
W_VIRALITY    = float(os.getenv("WEIGHT_VIRALITY",      0.25))
W_COMPETITION = float(os.getenv("WEIGHT_COMPETITION",   0.20))


# ──────────────────────────────────────────────
# INDIVIDUAL SCORE CALCULATORS
# ──────────────────────────────────────────────

def calc_volume_score(raw_score: float, source: str) -> float:
    """
    Normalise raw engagement signal to [0, 1].
    Different sources have very different magnitude ranges.
    """
    norms = {
        "reddit":           100_000,
        "google_trends":    100,
        "hacker_news":      5_000,
        "youtube_trending": 100,    # already pre-normalised
        "github_trending":  50_000,
        "gnews":            80,
        "rss":              80,
    }
    source_key = source.split("/")[0]
    max_val = norms.get(source_key, 1000)
    score = min(raw_score / max_val, 1.0)
    return round(score, 4)


def calc_recency_score(published_at: Optional[datetime]) -> float:
    if published_at is None:
        return 0.3

    # convert everything to UTC-aware
    now = datetime.now(timezone.utc)

    if published_at.tzinfo is None:
        published_at = published_at.replace(tzinfo=timezone.utc)

    age_hours = (now - published_at).total_seconds() / 3600

    age_hours = max(age_hours, 0)

    lam = math.log(2) / 24.0
    score = math.exp(-lam * age_hours)

    return round(max(score, 0.0), 4)


def calc_virality_score(item_data: Dict) -> float:
    """
    Estimate virality from engagement signals.
    High comments + high upvote ratio = viral.
    """
    score = 0.0
    signals = 0

    # Reddit: upvote ratio + comment velocity
    if "upvote_ratio" in item_data:
        score += item_data["upvote_ratio"]   # 0.0–1.0
        signals += 1
    if "num_comments" in item_data:
        # Normalise comments: 1000+ = max
        score += min(item_data["num_comments"] / 1000.0, 1.0)
        signals += 1

    # YouTube: like ratio
    if "likes" in item_data and "views" in item_data:
        if item_data["views"] > 0:
            lr = item_data["likes"] / item_data["views"]
            score += min(lr / 0.05, 1.0)   # 5% like ratio = max
            signals += 1

    # HN: comments per score ratio
    if "comments" in item_data:
        score += min(item_data["comments"] / 500.0, 1.0)
        signals += 1

    if signals == 0:
        return 0.4   # neutral default
    return round(score / signals, 4)


def calc_competition_score(title: str) -> float:
    """
    Estimate how saturated this topic is on YouTube.
    Higher score = more competition = lower net score contribution.

    Uses heuristics since we can't search YouTube programmatically
    without quota. Common high-competition topics are penalised.
    """
    HIGH_COMPETITION_TERMS = [
        "iphone", "android", "bitcoin", "crypto", "minecraft",
        "fortnite", "roblox", "tiktok", "tesla", "elon musk",
        "chatgpt", "ai", "news", "today", "breaking",
    ]
    LOW_COMPETITION_TERMS = [
        "science fact", "did you know", "psychology trick",
        "history of", "explained simply", "for beginners",
        "life hack", "science behind", "myth busted",
    ]
    title_lower = title.lower()
    score = 0.5   # neutral baseline

    for term in HIGH_COMPETITION_TERMS:
        if term in title_lower:
            score += 0.08
    for term in LOW_COMPETITION_TERMS:
        if term in title_lower:
            score -= 0.05

    return round(max(0.0, min(score, 1.0)), 4)


# ──────────────────────────────────────────────
# TOPIC FILTER (removes unsuitable topics)
# ──────────────────────────────────────────────

BLOCKLIST = [

    # Adult
    "nsfw","porn","sex","nude","onlyfans","escort",

    # Drugs
    "cocaine","heroin","meth","drug cartel",
    "overdose","fentanyl","opioid",

    # Violence
    "murder","killing","massacre","shooting",
    "gunman","gunmen","terrorist","terrorism",
    "isis","al qaeda","hamas","hostage",
    "bomb","bombing","explosion",
    "beheading","execution",

    # Crime
    "arrested","charged","criminal",
    "prison","jail","fraud","scam",
    "money laundering","kidnapping",

    # Self-harm
    "suicide","self harm",

    
    # Politics
    "election","president","prime minister",
    "democrat","republican",
    "parliament","congress",
    "political party","campaign",

    # Religion
    "church scandal",
    "religious conflict",
    "blasphemy",

    # Celebrity gossip
    "divorce",
    "celebrity","rapper",
    

    # Death
    "dies","died","death",
    "obituary","funeral","rip",

    # Natural disasters
    "earthquake","tsunami","hurricane",
    "tornado","flood disaster",

    # Court / legal
    "lawsuit","court case",
    "convicted","sentenced",

    # TV episode recap junk
    "episode",
    "season finale",
]

CONTENT_CATEGORIES = {

    # --------------------------------------------------
    # AI / TECH
    # --------------------------------------------------
    "ai_tech": [
        "ai", "artificial intelligence", "chatgpt", "openai",
        "anthropic", "claude", "gemini", "google",
        "microsoft", "meta", "tesla", "robot",
        "robotics", "automation", "software",
        "startup", "technology", "app", "coding",
        "machine learning", "deepmind"
    ],

    # --------------------------------------------------
    # SPACE
    # --------------------------------------------------
    "space": [
        "space", "nasa", "spacex", "mars",
        "moon", "astronaut", "rocket",
        "satellite", "galaxy", "planet",
        "black hole", "solar system",
        "telescope", "universe"
    ],

    # --------------------------------------------------
    # SCIENCE DISCOVERIES
    # --------------------------------------------------
    "science": [
        "scientists", "researchers", "research",
        "study", "discovery", "breakthrough",
        "experiment", "physics", "biology",
        "chemistry", "genetics", "fossil",
        "species", "evolution"
    ],

    # --------------------------------------------------
    # AMAZING FACTS
    # --------------------------------------------------
    "facts": [
        "did you know", "fact", "facts",
        "surprising", "unexpected",
        "unbelievable", "incredible",
        "shocking", "amazing",
        "interesting", "hidden"
    ],

    # --------------------------------------------------
    # ANIMALS
    # --------------------------------------------------
    "animals": [
        "animal", "wildlife", "shark",
        "whale", "dinosaur", "snake",
        "lion", "tiger", "elephant",
        "rare species", "ocean",
        "deep sea"
    ],

    # --------------------------------------------------
    # HISTORY
    # --------------------------------------------------
    "history": [
        "ancient", "roman", "egypt",
        "archaeology", "artifact",
        "historical", "history",
        "medieval", "civilization",
        "empire"
    ],

    # --------------------------------------------------
    # BUSINESS / STARTUPS
    # --------------------------------------------------
    "business": [
        "startup", "business",
        "founder", "company",
        "valuation", "investment",
        "funding", "acquisition",
        "ipo", "ceo"
    ],

    # --------------------------------------------------
    # FUTURE / INNOVATION
    # --------------------------------------------------
    "future": [
        "future", "innovation",
        "prototype", "next generation",
        "breakthrough technology",
        "new invention",
        "electric vehicle",
        "battery", "fusion"
    ],

    # --------------------------------------------------
    # MYSTERIES
    # --------------------------------------------------
    "mystery": [
        "mystery", "unknown",
        "unexplained", "strange",
        "bizarre", "hidden",
        "secret", "lost",
        "rare footage"
    ]
}

def is_suitable(title: str) -> Tuple[bool, str]:
    """Returns (suitable, category)."""
    tl = title.lower()
    for term in BLOCKLIST:
        if term in tl:
            return False, ""
    if len(title.strip()) < 10:
        return False, ""
    for cat, keywords in CONTENT_CATEGORIES.items():
        for kw in keywords:
            if kw in tl:
                return True, cat
    return True, "general"


# ──────────────────────────────────────────────
# MAIN RANKING ENGINE
# ──────────────────────────────────────────────

@dataclass
class ScoredTopic:
    title: str
    slug: str
    source: str
    final_score: float
    volume_score: float
    recency_score: float
    virality_score: float
    competition_score: float
    category: str
    keywords: List[str]
    published_at: Optional[datetime]
    raw_score: float

    def to_dict(self) -> dict:
        return {
            "title": self.title,
            "slug": self.slug,
            "source": self.source,
            "final_score": round(self.final_score, 3),
            "volume_score": self.volume_score,
            "recency_score": self.recency_score,
            "virality_score": self.virality_score,
            "competition_score": self.competition_score,
            "category": self.category,
            "keywords": self.keywords,
            "published_at": self.published_at.isoformat() if self.published_at else None,
            "raw_score": self.raw_score,
        }


class TopicRankingEngine:
    """
    Scores and ranks raw TrendItems.
    Formula:
        final_score =
            volume_score  * 0.30
          + recency_score * 0.25
          + virality_score* 0.25
          + (1 - competition_score) * 0.20
    """

    def score_item(self, item) -> Optional[ScoredTopic]:
        suitable, category = is_suitable(item.title)
        if not suitable:
            return None

        vs = calc_volume_score(item.score, item.source)
        rs = calc_recency_score(item.published_at)
        vv = calc_virality_score(item.extra)
        cs = calc_competition_score(item.title)

        final = (
            vs * W_VOLUME
          + rs * W_RECENCY
          + vv * W_VIRALITY
          + (1 - cs) * W_COMPETITION
        )

        return ScoredTopic(
            title=item.title,
            slug=item.slug,
            source=item.source,
            final_score=round(final * 100, 3),
            volume_score=vs,
            recency_score=rs,
            virality_score=vv,
            competition_score=cs,
            category=category or item.category,
            keywords=item.keywords,
            published_at=item.published_at,
            raw_score=item.score,
        )

    def rank(self, items: List) -> List[ScoredTopic]:
        scored = []
        for item in items:
            try:
                s = self.score_item(item)
                if s is not None:
                    scored.append(s)
            except Exception as e:
                logger.warning(f"Scoring error for '{item.title[:50]}': {e}")

        scored.sort(key=lambda x: x.final_score, reverse=True)
        logger.info(f"[ranking] Ranked {len(scored)} topics")
        if scored:
            top = scored[0]
            logger.info(
                f"[ranking] Top topic: '{top.title[:60]}' "
                f"score={top.final_score:.1f}"
            )
        return scored


# ──────────────────────────────────────────────
# DEDUPLICATION AGAINST DATABASE
# ──────────────────────────────────────────────

class TopicSelector:
    """
    Picks the best topic that hasn't been used in the last N days.
    """
    COOLDOWN_DAYS = 14    # don't reuse same topic within 2 weeks

    def select(self, ranked: List[ScoredTopic], db_session) -> Optional[ScoredTopic]:
        from src.database import Topic
        cutoff = datetime.utcnow() - timedelta(days=self.COOLDOWN_DAYS)

        used_slugs = set(
            row.slug for row in
            db_session.query(Topic.slug)
            .filter(Topic.used == True, Topic.used_at >= cutoff)
            .all()
        )

        # for candidate in ranked:
        #     if candidate.slug not in used_slugs:
        #         logger.info(f"[selector] Selected: '{candidate.title[:60]}'")
        #         return candidate
        

        available = [
            t for t in ranked
            if t.slug not in used_slugs
        ]

        if not available:
            logger.warning("No unused topics found")
            return None

        top_pool = available[:10]

        selected = random.choice(top_pool)

        logger.info(
            f"[selector] Randomly selected: '{selected.title[:60]}'"
        )

        return selected
        # logger.warning("[selector] All top topics recently used — using top anyway")
        # return ranked[0] if ranked else None

    def save_to_db(self, topic: ScoredTopic, db_session) -> int:
        """Upsert topic into DB; returns topic.id."""
        from src.database import Topic
        from sqlalchemy.dialects.sqlite import insert as sqlite_insert

        existing = db_session.query(Topic).filter_by(slug=topic.slug).first()
        if existing:
            existing.final_score = topic.final_score
            existing.status = "scored"
            db_session.commit()
            return existing.id

        t = Topic(
            title=topic.title,
            slug=topic.slug,
            source=topic.source,
            raw_score=topic.raw_score,
            final_score=topic.final_score,
            volume_score=topic.volume_score,
            recency_score=topic.recency_score,
            virality_score=topic.virality_score,
            competition_score=topic.competition_score,
            category=topic.category,
            keywords=",".join(topic.keywords),
            status="scored",
        )
        db_session.add(t)
        db_session.commit()
        return t.id


if __name__ == "__main__":
    # Quick test without real sources
    from src.trend.discovery import TrendItem
    items = [
        TrendItem("Scientists discover new planet", "rss/guardian",
                  score=80, published_at=datetime.utcnow() - timedelta(hours=2)),
        TrendItem("Bitcoin hits new record price", "reddit/finance",
                  score=15000, published_at=datetime.utcnow() - timedelta(hours=6),
                  extra={"upvote_ratio": 0.92, "num_comments": 3000}),
        TrendItem("AI writes entire novel in 10 minutes", "hacker_news",
                  score=2000, published_at=datetime.utcnow() - timedelta(hours=1),
                  extra={"comments": 450}),
    ]
    engine = TopicRankingEngine()
    ranked = engine.rank(items)
    for r in ranked:
        print(f"[{r.final_score:.1f}] {r.title}")
