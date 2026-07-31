"""
growth/optimizer.py — Growth optimization, A/B testing, and trend prediction.
"""
import os, json, math
from collections import defaultdict
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Tuple
from loguru import logger
from dotenv import load_dotenv
load_dotenv()

AB_ENABLED      = os.getenv("AB_TESTING_ENABLED", "true").lower() == "true"
AB_VARIANTS     = int(os.getenv("AB_TITLE_VARIANTS", "2"))
COOLDOWN_DAYS   = 14


# ──────────────────────────────────────────────
# TOPIC CLUSTERING
# Groups similar topics to avoid content overlap
# ──────────────────────────────────────────────

class TopicClusterer:
    """
    Simple keyword-overlap clustering.
    No ML dependency — uses Jaccard similarity.
    """
    SIMILARITY_THRESHOLD = 0.35

    def cluster(self, topics: List[Dict]) -> List[Dict]:
        """
        Assign cluster_id to each topic dict.
        Topics in the same cluster cover the same subject.
        """
        for t in topics:
            t.setdefault("cluster_id", None)
            t["_keywords"] = set(self._keywords(t.get("title", "")))

        clusters = []
        for topic in topics:
            assigned = False
            for cid, cluster in enumerate(clusters):
                rep = cluster[0]
                sim = self._jaccard(topic["_keywords"], rep["_keywords"])
                if sim >= self.SIMILARITY_THRESHOLD:
                    topic["cluster_id"] = cid
                    cluster.append(topic)
                    assigned = True
                    break
            if not assigned:
                new_cid = len(clusters)
                topic["cluster_id"] = new_cid
                clusters.append([topic])

        # Clean up temp field
        for t in topics:
            t.pop("_keywords", None)

        logger.info(f"[clustering] {len(topics)} topics → {len(clusters)} clusters")
        return topics

    def _keywords(self, text: str) -> List[str]:
        import re
        stop = {"the","a","an","is","in","on","at","to","of","and","or",
                "for","with","this","that","it","was","how","why","what",
                "did","you","know","most","have","just","new","about"}
        words = re.findall(r'\b[a-z]{3,}\b', text.lower())
        return [w for w in words if w not in stop]

    def _jaccard(self, a: set, b: set) -> float:
        if not a or not b:
            return 0.0
        return len(a & b) / len(a | b)


# ──────────────────────────────────────────────
# TREND PREDICTION
# Simple time-series: moving average + spike detection
# ──────────────────────────────────────────────

class TrendPredictor:
    """
    Predicts whether a topic's interest is rising or falling.
    Uses rolling average slope on score history.
    """

    def predict_trend(self, topic_slug: str, db_session) -> str:
        """
        Returns: 'rising' | 'falling' | 'stable' | 'unknown'
        """
        try:
            from src.database import Topic
            # Get last 5 scores for this topic slug (or similar)
            rows = (db_session.query(Topic.final_score, Topic.created_at)
                    .filter(Topic.slug == topic_slug)
                    .order_by(Topic.created_at.desc())
                    .limit(5).all())

            if len(rows) < 2:
                return "unknown"

            scores = [r[0] for r in reversed(rows)]
            slope  = self._slope(scores)

            if slope > 3.0:
                return "rising"
            elif slope < -3.0:
                return "falling"
            return "stable"

        except Exception:
            return "unknown"

    def _slope(self, values: List[float]) -> float:
        """Simple linear regression slope."""
        n = len(values)
        if n < 2:
            return 0.0
        x_mean = (n - 1) / 2
        y_mean = sum(values) / n
        num = sum((i - x_mean) * (v - y_mean) for i, v in enumerate(values))
        den = sum((i - x_mean) ** 2 for i in range(n))
        return num / den if den else 0.0

    def adjust_score(self, base_score: float, trend: str) -> float:
        """Boost/penalise score based on trend direction."""
        multipliers = {
            "rising":  1.25,
            "stable":  1.00,
            "falling": 0.75,
            "unknown": 0.95,
        }
        return base_score * multipliers.get(trend, 1.0)


# ──────────────────────────────────────────────
# A/B TITLE TESTING
# ──────────────────────────────────────────────

class ABTestManager:
    """
    Manages A/B title variants and tracks which performs better.
    Simple implementation: pick winner based on CTR after 48h.
    """

    def generate_variants(self, topic: str, base_title: str,
                           num: int = AB_VARIANTS) -> List[Dict]:
        """
        Generate title variants with different hook styles.
        Returns list of {variant_id, title, style}
        """
        import re
        keyword = " ".join(topic.split()[:5])
        variants_pool = [
            {"style": "number",     "title": f"5 Facts About {keyword} #Shorts"},
            {"style": "question",   "title": f"Did You Know This About {keyword}? #Shorts"},
            {"style": "shocking",   "title": f"This About {keyword} Will Shock You #Shorts"},
            {"style": "challenge",  "title": f"Most People Don't Know {keyword} #Shorts"},
            {"style": "mystery",    "title": f"The Untold Truth About {keyword} #Shorts"},
            {"style": "original",   "title": base_title},
        ]
        selected = variants_pool[:num]
        for i, v in enumerate(selected):
            v["variant_id"] = chr(65 + i)   # A, B, C…
            v["title"] = v["title"][:100]
        return selected

    def pick_winner(self, db_session, upload_ids: List[int]) -> Optional[int]:
        """
        Compare analytics for A/B variants.
        Returns upload_id of winner (highest CTR), or None if too early.
        """
        from src.database import Analytics, Upload
        from datetime import timedelta

        results = []
        for uid in upload_ids:
            upload = db_session.query(Upload).filter_by(id=uid).first()
            if not upload or not upload.uploaded_at:
                continue
            age_hours = (datetime.utcnow() - upload.uploaded_at).total_seconds() / 3600
            if age_hours < 48:
                logger.info(f"[ab_test] Upload {uid} only {age_hours:.0f}h old — too early")
                return None

            analytics = (db_session.query(Analytics)
                         .filter_by(upload_id=uid)
                         .order_by(Analytics.fetched_at.desc())
                         .first())
            if analytics:
                results.append((uid, analytics.ctr or analytics.views))

        if not results:
            return None

        winner_id, best_ctr = max(results, key=lambda x: x[1])
        logger.info(f"[ab_test] Winner: upload_id={winner_id}, CTR={best_ctr}")
        return winner_id


# ──────────────────────────────────────────────
# PERFORMANCE TRACKER
# ──────────────────────────────────────────────

class PerformanceTracker:
    """
    Fetches analytics from YouTube and stores in DB.
    Also detects best-performing topics/categories.
    """

    def fetch_and_save(self, db_session, uploader) -> int:
        """
        Fetch analytics for all uploads with YouTube IDs.
        Returns number of records updated.
        """
        from src.database import Upload, Analytics
        updated = 0
        uploads = (db_session.query(Upload)
                   .filter(Upload.youtube_id.isnot(None),
                           Upload.status == "success")
                   .all())

        for upload in uploads:
            try:
                stats = uploader.get_video_stats(upload.youtube_id)
                if not stats:
                    continue

                record = Analytics(
                    upload_id   = upload.id,
                    views       = stats.get("views", 0),
                    likes       = stats.get("likes", 0),
                    comments    = stats.get("comments", 0),
                )
                db_session.add(record)
                updated += 1
                logger.debug(f"[perf] {upload.youtube_id}: "
                             f"{stats.get('views', 0)} views")
            except Exception as e:
                logger.warning(f"[perf] Failed for {upload.youtube_id}: {e}")

        db_session.commit()
        logger.info(f"[perf] Updated analytics for {updated} videos")
        return updated

    def get_top_categories(self, db_session, days: int = 30) -> List[Dict]:
        """Return best-performing categories by average views."""
        from src.database import Analytics, Upload, Video, Topic
        from datetime import timedelta
        cutoff = datetime.utcnow() - timedelta(days=days)
        try:
            rows = (db_session.query(
                        Topic.category,
                        Analytics.views,
                    )
                    .join(Upload, Upload.id == Analytics.upload_id)
                    .join(Video,  Video.id  == Upload.video_id)
                    .join(Topic,  Topic.id  == Video.topic_id)
                    .filter(Analytics.fetched_at >= cutoff)
                    .all())

            cat_stats = defaultdict(list)
            for cat, views in rows:
                cat_stats[cat].append(views)

            result = [
                {
                    "category": cat,
                    "avg_views": round(sum(vs) / len(vs)),
                    "count": len(vs),
                }
                for cat, vs in cat_stats.items()
            ]
            result.sort(key=lambda x: x["avg_views"], reverse=True)
            return result
        except Exception as e:
            logger.warning(f"[perf] Category stats failed: {e}")
            return []

    def suggest_best_upload_time(self, db_session) -> str:
        """
        Find hour-of-day with highest average views.
        Returns string like "18:00 UTC"
        """
        from src.database import Analytics, Upload
        try:
            rows = (db_session.query(Upload.uploaded_at, Analytics.views)
                   .join(Analytics, Analytics.upload_id == Upload.id)
                   .filter(Upload.uploaded_at.isnot(None))
                   .all())
            if len(rows) < 5:
                return "18:00 UTC (default — not enough data yet)"

            hour_views = defaultdict(list)
            for uploaded_at, views in rows:
                if uploaded_at:
                    hour_views[uploaded_at.hour].append(views)

            best_hour = max(hour_views, key=lambda h: sum(hour_views[h]) / len(hour_views[h]))
            return f"{best_hour:02d}:00 UTC"
        except Exception:
            return "18:00 UTC (default)"


# ──────────────────────────────────────────────
# COMBINED OPTIMIZER
# ──────────────────────────────────────────────

class GrowthOptimizer:
    def __init__(self):
        self.clusterer  = TopicClusterer()
        self.predictor  = TrendPredictor()
        self.ab_manager = ABTestManager()
        self.tracker    = PerformanceTracker()

    def optimise_topic_list(self, topics: List[Dict],
                             db_session) -> List[Dict]:
        """
        Full optimisation pipeline for a list of ranked topics.
        1. Cluster
        2. Adjust scores by trend direction
        3. Re-sort
        """
        clustered = self.clusterer.cluster(topics)
        for t in clustered:
            trend  = self.predictor.predict_trend(t.get("slug", ""), db_session)
            t["trend_direction"] = trend
            t["adjusted_score"]  = self.predictor.adjust_score(
                t.get("final_score", 0), trend)

        clustered.sort(key=lambda x: x["adjusted_score"], reverse=True)
        return clustered

    def get_title_for_upload(self, topic: str, base_title: str,
                              variant: str = "A") -> str:
        """Get the title for a specific A/B variant."""
        if not AB_ENABLED:
            return base_title
        variants = self.ab_manager.generate_variants(topic, base_title)
        for v in variants:
            if v["variant_id"] == variant:
                return v["title"]
        return base_title
