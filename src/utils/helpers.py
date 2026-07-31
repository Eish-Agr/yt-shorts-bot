"""
utils/helpers.py — Shared utility functions used across the pipeline.
"""
import os, re, time, hashlib, shutil
from pathlib import Path
from typing import Optional
from loguru import logger


def slugify(text: str, max_len: int = 200) -> str:
    """Convert any string to a clean URL/DB-safe slug."""
    text = text.lower()
    text = re.sub(r'[^\w\s-]', '', text)
    text = re.sub(r'[\s_-]+', '-', text)
    text = text.strip('-')
    return text[:max_len]


def content_hash(text: str) -> str:
    """Short MD5 hash of content for dedup."""
    return hashlib.md5(text.encode('utf-8')).hexdigest()[:12]


def ensure_dir(path: str) -> str:
    Path(path).mkdir(parents=True, exist_ok=True)
    return path


def file_size_mb(path: str) -> float:
    try:
        return os.path.getsize(path) / 1_048_576
    except OSError:
        return 0.0


def clean_output_older_than(days: int = 7):
    """
    Remove video/audio/image files older than N days to save disk.
    Keeps the DB and config intact.
    """
    from datetime import datetime, timedelta
    cutoff = time.time() - days * 86400
    dirs   = ["output/videos", "output/audio", "output/images"]
    removed = 0
    for d in dirs:
        if not os.path.isdir(d):
            continue
        for f in Path(d).iterdir():
            if f.is_file() and f.stat().st_mtime < cutoff:
                f.unlink()
                removed += 1
    logger.info(f"[cleanup] Removed {removed} old output files (>{days}d)")
    return removed


def get_ffmpeg_version() -> Optional[str]:
    """Return FFmpeg version string or None if not found."""
    import subprocess
    try:
        r = subprocess.run(["ffmpeg", "-version"],
                           capture_output=True, text=True, timeout=5)
        first_line = r.stdout.split('\n')[0]
        return first_line.split('version ')[1].split(' ')[0]
    except Exception:
        return None


def check_all_dependencies() -> dict:
    """Quick health check — call at startup to verify environment."""
    results = {}

    # FFmpeg
    ffmpeg_v = get_ffmpeg_version()
    results["ffmpeg"] = {"ok": bool(ffmpeg_v), "version": ffmpeg_v}

    # Piper TTS
    piper = os.getenv("PIPER_BINARY", "./tools/piper/piper")
    results["piper"] = {
        "ok": Path(piper).exists() or bool(shutil.which("piper")),
        "path": piper,
    }

    # Ollama
    try:
        import requests
        r = requests.get(os.getenv("OLLAMA_HOST", "http://localhost:11434") + "/api/tags",
                         timeout=2)
        results["ollama"] = {"ok": r.status_code == 200}
    except Exception:
        results["ollama"] = {"ok": False, "note": "Not running (template fallback will be used)"}

    # Font
    font = os.getenv("FONT_PATH", "./assets/fonts/Montserrat-Bold.ttf")
    results["font"] = {"ok": Path(font).exists(), "path": font}

    # API keys
    results["api_keys"] = {
        "reddit":  bool(os.getenv("REDDIT_CLIENT_ID")),
        "pixabay": bool(os.getenv("PIXABAY_API_KEY")),
        "gnews":   bool(os.getenv("GNEWS_API_KEY")),
        "pexels":  bool(os.getenv("PEXELS_API_KEY")),
    }

    return results


if __name__ == "__main__":
    import json
    deps = check_all_dependencies()
    print(json.dumps(deps, indent=2))
