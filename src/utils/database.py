"""
database.py — SQLAlchemy models + SQLite schema
Handles all persistent state: topics, scripts, videos, uploads, analytics.
"""
import os
from datetime import datetime
from typing import Optional
from sqlalchemy import (
    create_engine, Column, Integer, String, Float,
    Boolean, DateTime, Text, ForeignKey, Index
)
from sqlalchemy.orm import declarative_base, sessionmaker, relationship
from dotenv import load_dotenv

load_dotenv()
Base = declarative_base()
DB_PATH = os.getenv("DB_PATH", "./data/bot.db")
os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)


# ──────────────────────────────────────────────
# MODELS
# ──────────────────────────────────────────────

class Topic(Base):
    """
    A trending topic candidate discovered from any source.
    """
    __tablename__ = "topics"

    id           = Column(Integer, primary_key=True, autoincrement=True)
    title        = Column(String(500), nullable=False)
    slug         = Column(String(500), unique=True, nullable=False)   # de-dup key
    source       = Column(String(100))                                 # reddit/gtrends/hn/…
    raw_score    = Column(Float, default=0.0)
    final_score  = Column(Float, default=0.0)

    # Scoring sub-scores
    volume_score    = Column(Float, default=0.0)
    recency_score   = Column(Float, default=0.0)
    virality_score  = Column(Float, default=0.0)
    competition_score = Column(Float, default=0.0)

    # Status lifecycle
    # new → scored → selected → scripted → produced → uploaded → archived
    status       = Column(String(50), default="new")
    used         = Column(Boolean, default=False)
    used_at      = Column(DateTime, nullable=True)
    created_at   = Column(DateTime, default=datetime.utcnow)
    discovered_at = Column(DateTime, default=datetime.utcnow)

    # Extra metadata
    keywords     = Column(Text, default="")       # comma-separated
    category     = Column(String(100), default="")
    cluster_id   = Column(Integer, nullable=True)  # for topic clustering

    # Relationships
    scripts      = relationship("Script", back_populates="topic")
    videos       = relationship("Video",  back_populates="topic")

    __table_args__ = (
        Index("ix_topics_status", "status"),
        Index("ix_topics_score",  "final_score"),
        Index("ix_topics_slug",   "slug", unique=True),
    )

    def __repr__(self):
        return f"<Topic id={self.id} title={self.title!r} score={self.final_score:.2f}>"


class Script(Base):
    """
    Generated script for a topic, including hook/body/CTA breakdown.
    """
    __tablename__ = "scripts"

    id           = Column(Integer, primary_key=True, autoincrement=True)
    topic_id     = Column(Integer, ForeignKey("topics.id"), nullable=False)
    duration_target = Column(Integer, default=60)       # 30, 60, or 90 seconds
    hook         = Column(Text, default="")
    body         = Column(Text, default="")
    cta          = Column(Text, default="")
    full_text    = Column(Text, default="")
    word_count   = Column(Integer, default=0)
    estimated_duration = Column(Float, default=0.0)     # seconds
    model_used   = Column(String(100), default="")      # ollama model or template
    version      = Column(Integer, default=1)           # for A/B variants
    created_at   = Column(DateTime, default=datetime.utcnow)

    topic        = relationship("Topic", back_populates="scripts")
    videos       = relationship("Video", back_populates="script")

    def __repr__(self):
        return f"<Script id={self.id} topic_id={self.topic_id} dur={self.duration_target}s>"


class Video(Base):
    """
    A produced video file ready for or already uploaded.
    """
    __tablename__ = "videos"

    id              = Column(Integer, primary_key=True, autoincrement=True)
    topic_id        = Column(Integer, ForeignKey("topics.id"), nullable=False)
    script_id       = Column(Integer, ForeignKey("scripts.id"), nullable=False)
    file_path       = Column(String(1000), default="")
    thumbnail_path  = Column(String(1000), default="")
    audio_path      = Column(String(1000), default="")
    duration        = Column(Float, default=0.0)        # actual seconds
    file_size_mb    = Column(Float, default=0.0)
    resolution      = Column(String(20), default="1080x1920")
    tts_engine      = Column(String(50), default="")
    visual_engine   = Column(String(50), default="")
    status          = Column(String(50), default="pending")  # pending/ready/uploaded/failed
    created_at      = Column(DateTime, default=datetime.utcnow)
    produced_at     = Column(DateTime, nullable=True)

    topic   = relationship("Topic",  back_populates="videos")
    script  = relationship("Script", back_populates="videos")
    upload  = relationship("Upload", back_populates="video", uselist=False)

    __table_args__ = (
        Index("ix_videos_status", "status"),
    )


class Upload(Base):
    """
    YouTube upload record and metadata.
    """
    __tablename__ = "uploads"

    id              = Column(Integer, primary_key=True, autoincrement=True)
    video_id        = Column(Integer, ForeignKey("videos.id"), nullable=False)
    youtube_id      = Column(String(50), unique=True, nullable=True)   # e.g. dQw4w9WgXcQ
    title           = Column(String(200), default="")
    description     = Column(Text, default="")
    tags            = Column(Text, default="")         # comma-separated
    category_id     = Column(String(10), default="28")
    privacy         = Column(String(20), default="public")
    uploaded_at     = Column(DateTime, nullable=True)
    status          = Column(String(50), default="pending")  # pending/success/failed
    error_message   = Column(Text, default="")
    retry_count     = Column(Integer, default=0)

    # A/B test fields
    title_variant   = Column(String(10), default="A")

    video = relationship("Video", back_populates="upload")

    __table_args__ = (
        Index("ix_uploads_youtube_id", "youtube_id"),
    )


class Analytics(Base):
    """
    YouTube performance metrics fetched periodically.
    """
    __tablename__ = "analytics"

    id              = Column(Integer, primary_key=True, autoincrement=True)
    upload_id       = Column(Integer, ForeignKey("uploads.id"), nullable=False)
    fetched_at      = Column(DateTime, default=datetime.utcnow)
    views           = Column(Integer, default=0)
    likes           = Column(Integer, default=0)
    comments        = Column(Integer, default=0)
    watch_time_hrs  = Column(Float, default=0.0)
    avg_view_pct    = Column(Float, default=0.0)     # average view duration %
    ctr             = Column(Float, default=0.0)     # click-through rate


class RunLog(Base):
    """
    One record per pipeline execution for monitoring / retries.
    """
    __tablename__ = "run_logs"

    id          = Column(Integer, primary_key=True, autoincrement=True)
    run_id      = Column(String(100), unique=True)
    started_at  = Column(DateTime, default=datetime.utcnow)
    finished_at = Column(DateTime, nullable=True)
    status      = Column(String(50), default="running")   # running/success/failed
    topic_id    = Column(Integer, nullable=True)
    video_id    = Column(Integer, nullable=True)
    upload_id   = Column(Integer, nullable=True)
    error       = Column(Text, default="")
    steps_log   = Column(Text, default="")    # JSON list of step statuses


# ──────────────────────────────────────────────
# ENGINE + SESSION FACTORY
# ──────────────────────────────────────────────

def get_engine(db_path: str = DB_PATH):
    url = f"sqlite:///{db_path}"
    return create_engine(
        url,
        connect_args={"check_same_thread": False},
        echo=False,
    )


def init_db(db_path: str = DB_PATH):
    """Create all tables if they don't exist."""
    engine = get_engine(db_path)
    Base.metadata.create_all(engine)
    return engine


def get_session(engine=None):
    if engine is None:
        engine = get_engine()
    Session = sessionmaker(bind=engine, autoflush=True, autocommit=False)
    return Session()


# Run this file directly to initialise the database
if __name__ == "__main__":
    engine = init_db()
    print(f"✅ Database initialised at: {DB_PATH}")
    print("Tables:", list(Base.metadata.tables.keys()))
