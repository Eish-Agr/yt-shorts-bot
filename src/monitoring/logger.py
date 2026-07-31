"""
monitoring/logger.py — Centralized logging, retry logic, alerting,
                        and pipeline health monitoring.
"""
import os, json, time, traceback, uuid
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional, Any, Dict
from functools import wraps

from loguru import logger
from tenacity import (
    retry, stop_after_attempt, wait_exponential,
    retry_if_exception_type, before_sleep_log
)
import logging
from dotenv import load_dotenv
load_dotenv()

LOG_LEVEL  = os.getenv("LOG_LEVEL", "INFO")
LOG_DIR    = Path("./logs")
LOG_DIR.mkdir(parents=True, exist_ok=True)

DISCORD_WEBHOOK = os.getenv("DISCORD_WEBHOOK", "")
TELEGRAM_TOKEN  = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT   = os.getenv("TELEGRAM_CHAT_ID", "")


# ──────────────────────────────────────────────
# LOGURU SETUP
# ──────────────────────────────────────────────

def setup_logging(run_id: str = ""):
    """Configure loguru: console + rotating file + error file."""
    logger.remove()

    # Console: colourful, concise
    logger.add(
        sink=lambda msg: print(msg, end=""),
        format=(
            "<green>{time:HH:mm:ss}</green> | "
            "<level>{level: <7}</level> | "
            "<cyan>{name}:{line}</cyan> — <level>{message}</level>"
        ),
        level=LOG_LEVEL,
        colorize=True,
    )

    # Rotating daily log file
    log_file = LOG_DIR / "bot_{time:YYYY-MM-DD}.log"
    logger.add(
        str(log_file),
        rotation="00:00",       # new file each day
        retention="14 days",
        level="DEBUG",
        format="{time:YYYY-MM-DD HH:mm:ss} | {level: <7} | {name}:{line} | {message}",
        encoding="utf-8",
    )

    # Errors only: separate file for quick debugging
    error_file = LOG_DIR / "errors_{time:YYYY-MM-DD}.log"
    logger.add(
        str(error_file),
        rotation="00:00",
        retention="30 days",
        level="ERROR",
        format="{time} | {level} | {name}:{line} | {message}\n{exception}",
        encoding="utf-8",
    )

    if run_id:
        # Per-run log for this pipeline execution
        run_log = LOG_DIR / f"run_{run_id}.log"
        logger.add(
            str(run_log),
            level="DEBUG",
            format="{time:HH:mm:ss} | {level: <7} | {message}",
            encoding="utf-8",
        )

    return logger


# ──────────────────────────────────────────────
# RUN TRACKER (persists to DB)
# ──────────────────────────────────────────────

class RunTracker:
    """
    Tracks one pipeline execution end-to-end.
    Writes status to DB + log file.
    """
    STEPS = [
        "trend_discovery",
        "topic_ranking",
        "topic_selection",
        "script_generation",
        "voice_synthesis",
        "visual_generation",
        "video_assembly",
        "thumbnail_generation",
        "youtube_upload",
        "analytics_save",
    ]

    def __init__(self, db_session=None):
        self.run_id     = f"run_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
        self.db_session = db_session
        self.steps_log  = {}
        self.started_at = datetime.utcnow()
        self.topic_id   = None
        self.video_id   = None
        self.upload_id  = None

        if db_session:
            self._save_run("running")

    def step_start(self, step: str):
        logger.info(f"[pipeline] ▶ Step: {step}")
        self.steps_log[step] = {"status": "running", "started": _now()}

    def step_ok(self, step: str, detail: str = ""):
        msg = f"[pipeline] ✅ {step}" + (f" — {detail}" if detail else "")
        logger.info(msg)
        self.steps_log[step] = {"status": "ok", "detail": detail,
                                 "finished": _now()}

    def step_fail(self, step: str, error: str = ""):
        msg = f"[pipeline] ❌ {step}" + (f" — {error}" if error else "")
        logger.error(msg)
        self.steps_log[step] = {"status": "failed", "error": error,
                                  "finished": _now()}

    def step_skip(self, step: str, reason: str = ""):
        logger.warning(f"[pipeline] ⏭ {step} skipped — {reason}")
        self.steps_log[step] = {"status": "skipped", "reason": reason}

    def finish(self, status: str = "success", error: str = ""):
        self.finished_at = datetime.utcnow()
        elapsed = (self.finished_at - self.started_at).total_seconds()
        logger.info(f"[pipeline] Run {self.run_id} finished: {status} in {elapsed:.0f}s")
        if self.db_session:
            self._save_run(status, error)

    def _save_run(self, status: str, error: str = ""):
        try:
            from src.database import RunLog
            existing = (self.db_session.query(RunLog)
                        .filter_by(run_id=self.run_id).first())
            if existing:
                existing.status     = status
                existing.error      = error[:2000]
                existing.steps_log  = json.dumps(self.steps_log)
                existing.finished_at = datetime.utcnow()
                existing.topic_id   = self.topic_id
                existing.video_id   = self.video_id
                existing.upload_id  = self.upload_id
            else:
                rl = RunLog(
                    run_id=self.run_id,
                    status=status,
                    error=error[:2000],
                    steps_log=json.dumps(self.steps_log),
                    topic_id=self.topic_id,
                )
                self.db_session.add(rl)
            self.db_session.commit()
        except Exception as e:
            logger.warning(f"[tracker] DB save failed: {e}")


def _now() -> str:
    return datetime.utcnow().isoformat()


# ──────────────────────────────────────────────
# RETRY DECORATOR
# ──────────────────────────────────────────────

def with_retry(max_attempts: int = 3, wait_min: float = 2.0,
               wait_max: float = 30.0):
    """
    Decorator: retry a function on any exception with exponential backoff.
    Usage:
        @with_retry(max_attempts=3)
        def upload_video(...): ...
    """
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            for attempt in range(1, max_attempts + 1):
                try:
                    return fn(*args, **kwargs)
                except Exception as e:
                    if attempt == max_attempts:
                        logger.error(
                            f"[retry] {fn.__name__} failed after "
                            f"{max_attempts} attempts: {e}"
                        )
                        raise
                    wait = min(wait_min * (2 ** (attempt - 1)), wait_max)
                    logger.warning(
                        f"[retry] {fn.__name__} attempt {attempt} failed: {e}. "
                        f"Retrying in {wait:.0f}s..."
                    )
                    time.sleep(wait)
        return wrapper
    return decorator


# ──────────────────────────────────────────────
# DUPLICATE PREVENTION
# ──────────────────────────────────────────────

class DuplicateGuard:
    """
    Prevents running the same topic twice within the cooldown window.
    Uses both DB check and a local bloom-filter-like set.
    """
    _seen_this_session: set = set()

    def is_duplicate(self, slug: str, db_session,
                      cooldown_days: int = 14) -> bool:
        if slug in self._seen_this_session:
            return True
        try:
            from src.database import Topic
            from datetime import timedelta
            cutoff = datetime.utcnow() - timedelta(days=cooldown_days)
            existing = (db_session.query(Topic)
                        .filter(Topic.slug == slug,
                                Topic.used == True,
                                Topic.used_at >= cutoff)
                        .first())
            return existing is not None
        except Exception:
            return False

    def mark_used(self, slug: str):
        self._seen_this_session.add(slug)


# ──────────────────────────────────────────────
# ALERTING
# ──────────────────────────────────────────────

def send_discord_alert(message: str, is_error: bool = False):
    """Send notification to Discord webhook."""
    if not DISCORD_WEBHOOK:
        return
    import requests
    color = 0xFF4444 if is_error else 0x44FF88
    payload = {
        "embeds": [{
            "title": "🤖 YT Shorts Bot",
            "description": message[:2000],
            "color": color,
            "timestamp": datetime.utcnow().isoformat(),
        }]
    }
    try:
        requests.post(DISCORD_WEBHOOK, json=payload, timeout=10)
    except Exception as e:
        logger.warning(f"[discord] Alert failed: {e}")


def send_telegram_alert(message: str):
    """Send notification to Telegram bot."""
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT:
        return
    import requests
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    try:
        requests.post(url, json={
            "chat_id": TELEGRAM_CHAT,
            "text": f"🤖 YT Shorts Bot\n\n{message}",
            "parse_mode": "Markdown",
        }, timeout=10)
    except Exception as e:
        logger.warning(f"[telegram] Alert failed: {e}")


def notify(message: str, is_error: bool = False):
    """Send to all configured notification channels."""
    if is_error:
        logger.error(f"[notify] {message}")
    else:
        logger.info(f"[notify] {message}")
    send_discord_alert(message, is_error)
    send_telegram_alert(message)


# ──────────────────────────────────────────────
# PIPELINE HEALTH SUMMARY
# ──────────────────────────────────────────────

def get_pipeline_summary(db_session) -> Dict:
    """Return a health summary dict for the last 7 days."""
    from src.database import RunLog, Upload, Video
    from datetime import timedelta
    cutoff = datetime.utcnow() - timedelta(days=7)
    try:
        runs   = db_session.query(RunLog).filter(RunLog.started_at >= cutoff).all()
        ok     = sum(1 for r in runs if r.status == "success")
        failed = sum(1 for r in runs if r.status == "failed")
        uploads = (db_session.query(Upload)
                   .filter(Upload.uploaded_at >= cutoff,
                           Upload.status == "success").all())
        return {
            "last_7_days": {
                "runs_total":   len(runs),
                "runs_ok":      ok,
                "runs_failed":  failed,
                "success_rate": f"{ok/len(runs)*100:.0f}%" if runs else "N/A",
                "videos_uploaded": len(uploads),
            }
        }
    except Exception as e:
        return {"error": str(e)}
