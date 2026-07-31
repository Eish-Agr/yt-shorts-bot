"""
main.py — The complete YouTube Shorts automation pipeline.

Single entry point. Runs all 9 stages in sequence:
  1. Trend Discovery
  2. Topic Ranking & Dedup
  3. Script Generation
  4. Voice Synthesis
  5. Visual Generation
  6. Video Assembly
  7. Thumbnail Generation
  8. YouTube Upload
  9. Analytics Save

Usage:
  python main.py              # Run once now
  python main.py --schedule   # Run on schedule (every N hours from .env)
  python main.py --dry-run    # Run everything EXCEPT the YouTube upload
  python main.py --auth       # Just authenticate with YouTube
  python main.py --stats      # Show pipeline stats
"""
import os, sys, json, time, uuid, argparse
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv
load_dotenv()

# ── Bootstrap logging before anything else ──
from src.monitoring.logger import setup_logging, RunTracker, DuplicateGuard, notify
run_id  = f"run_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
log     = setup_logging(run_id)

from loguru import logger


# ──────────────────────────────────────────────
# PIPELINE STAGES
# ──────────────────────────────────────────────

def stage_trend_discovery():
    """Stage 1: Collect trending topics from all sources."""
    from src.trend.discovery import TrendAggregator
    agg   = TrendAggregator()
    items = agg.collect_all()
    logger.info(f"[stage1] Collected {len(items)} raw trend items")
    return items


def stage_rank_and_select(items, db_session):
    """Stage 2: Score, rank, and select best unseen topic."""
    from src.ranking.engine import TopicRankingEngine, TopicSelector
    engine   = TopicRankingEngine()
    selector = TopicSelector()
    guard    = DuplicateGuard()

    ranked = engine.rank(items)
    if not ranked:
        raise RuntimeError("No topics could be scored")

    # Save top-30 to DB
    for scored in ranked[:30]:
        selector.save_to_db(scored, db_session)

    # Pick best unUsed topic
    topic = selector.select(ranked, db_session)
    if not topic:
        raise RuntimeError("All top topics recently used — try again later")

    if guard.is_duplicate(topic.slug, db_session):
        raise RuntimeError(f"Topic '{topic.title[:50]}' is a recent duplicate")

    # Mark as selected in DB
    from src.database import Topic
    db_topic = db_session.query(Topic).filter_by(slug=topic.slug).first()
    if db_topic:
        db_topic.status = "selected"
        db_session.commit()
        topic_db_id = db_topic.id
    else:
        topic_db_id = None

    guard.mark_used(topic.slug)
    logger.info(f"[stage2] Selected topic: '{topic.title[:70]}'")
    logger.info(f"[stage2] Score: {topic.final_score:.1f} | Category: {topic.category}")
    return topic, topic_db_id


def stage_generate_script(topic, db_session, topic_db_id):
    """Stage 3: Generate voiceover script with Ollama / template."""
    from src.script.generator import ScriptGenerator
    from src.database import Script

    duration = int(os.getenv("VIDEO_DURATION", "60"))   # 30, 60, or 90
    gen      = ScriptGenerator()

    # Generate 2 hook style variants for A/B
    script = gen.generate(topic.title, duration=duration, hook_style="question")

    # Save script to DB
    if topic_db_id:
        db_script = Script(
            topic_id           = topic_db_id,
            duration_target    = duration,
            hook               = script.get("hook", "")[:500],
            body               = script.get("body", "")[:2000],
            cta                = script.get("cta", "")[:300],
            full_text          = script.get("full_script", "")[:3000],
            word_count         = script.get("word_count", 0),
            estimated_duration = script.get("estimated_duration", 0.0),
            model_used         = script.get("model_used", "unknown"),
        )
        db_session.add(db_script)
        db_session.commit()
        script_db_id = db_script.id
    else:
        script_db_id = None

    logger.info(f"[stage3] Script: {script.get('word_count', 0)} words "
                f"≈ {script.get('estimated_duration', 0):.0f}s "
                f"(model: {script.get('model_used', '?')})")
    return script, script_db_id


def stage_voice_synthesis(script, run_id):
    """Stage 4: Convert script text to WAV audio."""
    from src.voice.synthesis import VoiceGenerator
    audio_dir  = Path(os.getenv("OUTPUT_DIR", "./output")) / "audio"
    audio_dir.mkdir(parents=True, exist_ok=True)
    audio_path = str(audio_dir / f"{run_id}.wav")

    gen = VoiceGenerator()
    full_text = script.get("full_script", script.get("full_text", ""))
    success, engine_used = gen.generate(full_text, audio_path)

    if not success or not os.path.exists(audio_path):
        raise RuntimeError(f"Voice synthesis failed (engine: {engine_used})")

    logger.info(f"[stage4] Audio: {audio_path} (engine: {engine_used})")
    return audio_path, engine_used


def stage_visual_generation(topic, script, run_id):
    """Stage 5: Download / generate images for each scene."""
    from src.visual.generator import VisualGenerator
    gen  = VisualGenerator()
    plan = gen.generate_for_script(
        topic.title,
        script,
        run_id=run_id,
        num_scenes=8,
    )
    image_paths = [s.image_path for s in plan.scenes if s.image_path]
    if not image_paths:
        raise RuntimeError("No visual scenes generated")
    logger.info(f"[stage5] {len(image_paths)} images ready")
    return image_paths


def stage_video_assembly(image_paths, audio_path, script, run_id, topic):
    """Stage 6: Assemble final 1080x1920 video with captions."""
    from src.video.assembler import VideoAssembler
    asm = VideoAssembler(use_moviepy=False)  # Use FFmpeg for speed
    video_path = asm.assemble(
        scenes_images = image_paths,
        voice_path    = audio_path,
        script_text   = script.get("full_script", ""),
        run_id        = run_id,
        music_category = topic.category,
    )
    if not video_path or not os.path.exists(video_path):
        raise RuntimeError("Video assembly failed")

    info = asm.get_video_info(video_path)
    logger.info(f"[stage6] Video: {video_path} "
                f"({info['duration']:.0f}s, {info['size_mb']:.1f} MB)")
    return video_path, info


def stage_thumbnail_generation(topic, script, run_id, image_paths):
    """Stage 7: Generate 1280x720 thumbnail."""
    from src.thumbnail.generator import ThumbnailGenerator
    gen       = ThumbnailGenerator()
    hero_img  = image_paths[0] if image_paths else None
    thumb_path = gen.generate(
        topic   = topic.title,
        run_id  = run_id,
        script  = script,
        scene_image_path = hero_img,
    )
    logger.info(f"[stage7] Thumbnail: {thumb_path}")
    return thumb_path


def stage_youtube_upload(topic, script, video_path, thumb_path,
                          db_session, script_db_id, topic_db_id,
                          video_info, engine_used, dry_run=False):
    """Stage 8: Upload to YouTube with metadata."""
    from src.script.generator import ScriptGenerator
    from src.database import Video, Upload

    # Build metadata
    sg          = ScriptGenerator()
    base_title  = topic.title[:90]
    description = sg.generate_description(topic.title, script)
    hashtags    = sg.generate_hashtags(topic.title, topic.category)

    # A/B variant A for first upload
    from src.growth.optimizer import GrowthOptimizer
    opt   = GrowthOptimizer()
    title = opt.get_title_for_upload(topic.title, base_title, variant="A")

    tags_list = [t.lstrip("#") for t in hashtags.split()[:20]]

    # Save Video record
    if topic_db_id and script_db_id:
        db_video = Video(
            topic_id       = topic_db_id,
            script_id      = script_db_id,
            file_path      = video_path,
            thumbnail_path = thumb_path or "",
            audio_path     = "",
            duration       = video_info.get("duration", 0),
            file_size_mb   = video_info.get("size_mb", 0),
            tts_engine     = engine_used,
            visual_engine  = os.getenv("VISUAL_ENGINE", "mixed"),
            status         = "ready",
            produced_at    = datetime.utcnow(),
        )
        db_session.add(db_video)
        db_session.commit()
        db_video_id = db_video.id
    else:
        db_video_id = None

    if dry_run:

        if topic_db_id:
            from src.database import Topic

            t = db_session.query(Topic).filter_by(id=topic_db_id).first()

            if t:
                t.used = True
                t.used_at = datetime.utcnow()
                t.status = "produced"

                db_session.commit()

        logger.info("[stage8] DRY RUN — skipping YouTube upload")
        logger.info(f"[stage8] Would upload: {title[:70]}")
        return None, None

    # Upload
    from src.upload.youtube import YouTubeUploader
    uploader = YouTubeUploader()

    try:
        yt_id = uploader.upload_video(
            video_path       = video_path,
            title            = title,
            description      = description,
            tags             = tags_list,
            thumbnail_path   = thumb_path,
            privacy          = os.getenv("YT_PRIVACY", "public"),
        )
    except Exception as e:
        logger.error(f"[stage8] Upload exception: {e}")
        yt_id = None

    # Save Upload record
    if db_video_id:
        db_upload = Upload(
            video_id    = db_video_id,
            youtube_id  = yt_id,
            title       = title,
            description = description,
            tags        = ",".join(tags_list),
            status      = "success" if yt_id else "failed",
            uploaded_at = datetime.utcnow() if yt_id else None,
            error_message = "" if yt_id else "Upload returned no ID",
            title_variant = "A",
        )
        db_session.add(db_upload)

        if yt_id and topic_db_id:
            from src.database import Topic
            t = db_session.query(Topic).filter_by(id=topic_db_id).first()
            if t:
                t.used    = True
                t.used_at = datetime.utcnow()
                t.status  = "uploaded"

        db_session.commit()
        db_upload_id = db_upload.id
    else:
        db_upload_id = None

    if yt_id:
        url = f"https://youtu.be/{yt_id}"
        logger.info(f"[stage8] ✅ Uploaded: {url}")
        notify(f"✅ New Short uploaded!\n*{title}*\n{url}")
    else:
        logger.error("[stage8] Upload failed — video saved locally")

    return yt_id, db_upload_id


# ──────────────────────────────────────────────
# FULL PIPELINE
# ──────────────────────────────────────────────

def run_pipeline(dry_run: bool = False) -> dict:
    """
    Execute the complete end-to-end pipeline.
    Returns a result dict summarising what happened.
    """
    from src.database import init_db, get_session
    engine     = init_db()
    db_session = get_session(engine)
    tracker    = RunTracker(db_session)
    tracker.run_id = run_id

    result = {"run_id": run_id, "status": "failed"}

    try:
        # ── Stage 1: Trends ──
        tracker.step_start("trend_discovery")
        items = stage_trend_discovery()
        tracker.step_ok("trend_discovery", f"{len(items)} items")

        # ── Stage 2: Rank + Select ──
        tracker.step_start("topic_ranking")
        topic, topic_db_id = stage_rank_and_select(items, db_session)
        tracker.topic_id = topic_db_id
        tracker.step_ok("topic_ranking", topic.title[:60])

        # ── Stage 3: Script ──
        tracker.step_start("script_generation")
        script, script_db_id = stage_generate_script(topic, db_session, topic_db_id)
        tracker.step_ok("script_generation",
                        f"{script.get('word_count',0)} words / {script.get('estimated_duration',0):.0f}s")

        # ── Stage 4: Voice ──
        tracker.step_start("voice_synthesis")
        audio_path, engine_used = stage_voice_synthesis(script, run_id)
        tracker.step_ok("voice_synthesis", engine_used)

        # ── Stage 5: Visuals ──
        tracker.step_start("visual_generation")
        image_paths = stage_visual_generation(topic, script, run_id)
        tracker.step_ok("visual_generation", f"{len(image_paths)} scenes")

        # ── Stage 6: Video ──
        tracker.step_start("video_assembly")
        video_path, video_info = stage_video_assembly(
            image_paths, audio_path, script, run_id, topic)
        tracker.step_ok("video_assembly",
                        f"{video_info['duration']:.0f}s / {video_info['size_mb']:.1f}MB")

        # ── Stage 7: Thumbnail ──
        tracker.step_start("thumbnail_generation")
        thumb_path = stage_thumbnail_generation(topic, script, run_id, image_paths)
        tracker.step_ok("thumbnail_generation")

        # ── Stage 8: Upload ──
        tracker.step_start("youtube_upload")
        yt_id, db_upload_id = stage_youtube_upload(
            topic, script, video_path, thumb_path,
            db_session, script_db_id, topic_db_id,
            video_info, engine_used, dry_run=dry_run,
        )
        tracker.upload_id = db_upload_id
        tracker.step_ok("youtube_upload",
                        f"https://youtu.be/{yt_id}" if yt_id else "dry-run")

        result.update({
            "status":     "success",
            "topic":      topic.title,
            "score":      topic.final_score,
            "video":      video_path,
            "thumbnail":  thumb_path,
            "youtube_id": yt_id,
            "url":        f"https://youtu.be/{yt_id}" if yt_id else None,
        })
        tracker.finish("success")
        logger.info("=" * 60)
        logger.info(f"🎉 Pipeline complete! Run ID: {run_id}")
        if yt_id:
            logger.info(f"📺 Watch: https://youtu.be/{yt_id}")
        logger.info("=" * 60)

    except Exception as e:
        import traceback
        err = f"{type(e).__name__}: {e}"
        tb  = traceback.format_exc()
        logger.error(f"[pipeline] FATAL: {err}\n{tb}")
        tracker.finish("failed", err)
        notify(f"❌ Pipeline failed: {err}", is_error=True)
        result["error"] = err

    finally:
        try:
            db_session.close()
        except Exception:
            pass

    return result


# ──────────────────────────────────────────────
# SCHEDULER
# ──────────────────────────────────────────────

def run_scheduler():
    """Run the pipeline on a recurring schedule using APScheduler."""
    from apscheduler.schedulers.blocking import BlockingScheduler
    import pytz

    hours   = int(os.getenv("SCHEDULE_HOURS", "6"))
    max_day = int(os.getenv("MAX_VIDEOS_PER_DAY", "4"))

    logger.info(f"[scheduler] Starting — every {hours}h, max {max_day}/day")

    scheduler = BlockingScheduler(timezone=pytz.utc)
    run_count = {"today": 0, "date": datetime.utcnow().date()}

    def scheduled_run():
        today = datetime.utcnow().date()
        if run_count["date"] != today:
            run_count["today"] = 0
            run_count["date"]  = today

        if run_count["today"] >= max_day:
            logger.info(f"[scheduler] Daily limit reached ({max_day}/day)")
            return

        logger.info(f"[scheduler] ⏰ Scheduled run #{run_count['today']+1} of {max_day}")
        result = run_pipeline()
        if result.get("status") == "success":
            run_count["today"] += 1

    # Run immediately on start, then every N hours
    scheduler.add_job(scheduled_run, "interval", hours=hours,
                      next_run_time=datetime.utcnow())
    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        logger.info("[scheduler] Stopped by user")


# ──────────────────────────────────────────────
# CLI
# ──────────────────────────────────────────────

def print_stats():
    """Print pipeline stats from DB."""
    from src.database import init_db, get_session
    from src.monitoring.logger import get_pipeline_summary
    engine  = init_db()
    session = get_session(engine)
    summary = get_pipeline_summary(session)
    print(json.dumps(summary, indent=2))
    session.close()


def main():
    parser = argparse.ArgumentParser(
        description="YouTube Shorts Automation Bot",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python main.py               # Run once right now
  python main.py --dry-run     # Run without uploading
  python main.py --schedule    # Start scheduler
  python main.py --auth        # Authenticate with YouTube
  python main.py --stats       # Show 7-day stats
        """,
    )
    parser.add_argument("--schedule", action="store_true",
                        help="Run on a recurring schedule")
    parser.add_argument("--dry-run",  action="store_true",
                        help="Run all stages except YouTube upload")
    parser.add_argument("--auth",     action="store_true",
                        help="Authenticate with YouTube (run once)")
    parser.add_argument("--stats",    action="store_true",
                        help="Show pipeline stats")
    parser.add_argument("--init-db",  action="store_true",
                        help="Initialise the database")

    args = parser.parse_args()

    if args.auth:
        from src.upload.youtube import get_authenticated_service
        svc = get_authenticated_service()
        print("✅ YouTube authentication successful.")
        return

    if args.stats:
        print_stats()
        return

    if args.init_db:
        from src.database import init_db
        init_db()
        print("✅ Database initialised.")
        return

    if args.schedule:
        run_scheduler()
    else:
        result = run_pipeline(dry_run=args.dry_run)
        if result["status"] == "success":
            print(f"\n✅ Done! Topic: {result['topic']}")
            if result.get("url"):
                print(f"📺 URL: {result['url']}")
        else:
            print(f"\n❌ Failed: {result.get('error', 'unknown error')}")
            sys.exit(1)


if __name__ == "__main__":
    main()
