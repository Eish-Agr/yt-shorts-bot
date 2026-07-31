"""
video/assembler.py — YouTube Shorts video assembly
Creates 1080x1920 vertical videos with:
  - Voice-synced captions
  - Ken Burns zoom effects
  - Scene transitions (fade/slide/zoom)
  - Background music at low volume
  - Animated text captions

Requires: ffmpeg installed and on PATH, moviepy, Pillow
Install FFmpeg on Windows: https://ffmpeg.org/download.html
  or: winget install ffmpeg
  or: choco install ffmpeg
"""
import os, re, json, math, shutil, subprocess, textwrap
from pathlib import Path
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass
from loguru import logger
from dotenv import load_dotenv
load_dotenv()

VIDEO_W       = int(os.getenv("VIDEO_WIDTH",  "1080"))
VIDEO_H       = int(os.getenv("VIDEO_HEIGHT", "1920"))
FPS           = int(os.getenv("VIDEO_FPS",    "30"))
VIDEO_BITRATE = os.getenv("VIDEO_BITRATE",    "4000k")
AUDIO_BITRATE = os.getenv("AUDIO_BITRATE",    "192k")
CAPTION_SIZE  = int(os.getenv("CAPTION_FONT_SIZE", "52"))
FONT_PATH     = os.getenv("FONT_PATH", "./assets/fonts/Montserrat-Bold.ttf")
CAPTION_COLOR = os.getenv("CAPTION_COLOR", "white")
BG_MUSIC_VOL  = float(os.getenv("BACKGROUND_MUSIC_VOL", "0.15"))
VOICE_VOL     = float(os.getenv("VOICE_VOL", "1.0"))
TRANSITION    = os.getenv("DEFAULT_TRANSITION", "fade")
TRANS_DUR     = float(os.getenv("TRANSITION_DURATION", "0.4"))
OUTPUT_DIR    = Path(os.getenv("OUTPUT_DIR", "./output"))
VIDEOS_DIR    = OUTPUT_DIR / "videos"
MUSIC_DIR     = Path("./assets/music")

VIDEOS_DIR.mkdir(parents=True, exist_ok=True)


# ──────────────────────────────────────────────
# CAPTION UTILITIES
# ──────────────────────────────────────────────

def chunk_text_for_captions(full_text: str, audio_duration: float,
                             max_words: int = 5) -> List[Dict]:
    """
    Split full script into caption chunks with timestamps.
    Returns: [{text, start, end, words}]
    """
    words = full_text.split()
    wps   = len(words) / audio_duration if audio_duration > 0 else 2.33

    chunks = []
    i = 0
    while i < len(words):
        chunk_words = words[i:i + max_words]
        chunk_text  = " ".join(chunk_words)
        start       = round(i / wps, 3)
        end         = round((i + len(chunk_words)) / wps, 3)
        chunks.append({"text": chunk_text, "start": start, "end": end})
        i += max_words
    return chunks


def create_srt(chunks: List[Dict], output_path: str):
    """Generate SRT subtitle file from caption chunks."""
    def fmt(s: float) -> str:
        h = int(s // 3600)
        m = int((s % 3600) // 60)
        sec = int(s % 60)
        ms = int((s % 1) * 1000)
        return f"{h:02d}:{m:02d}:{sec:02d},{ms:03d}"

    with open(output_path, "w", encoding="utf-8") as f:
        for i, chunk in enumerate(chunks, 1):
            f.write(f"{i}\n")
            f.write(f"{fmt(chunk['start'])} --> {fmt(chunk['end'])}\n")
            f.write(f"{chunk['text']}\n\n")
    return output_path


def create_ass_subtitles(chunks: List[Dict], output_path: str):
    """
    Generate ASS subtitle file with styled captions.
    ASS gives better control: bold text, outline, shadow.
    """
    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {VIDEO_W}
PlayResY: {VIDEO_H}
WrapStyle: 1

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Montserrat,{CAPTION_SIZE},&H00FFFFFF,&H000000FF,&H00000000,&H80000000,-1,0,0,1,3,1,2,80,80,200,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    def fmt(s: float) -> str:
        h = int(s // 3600)
        m = int((s % 3600) // 60)
        sec = s % 60
        return f"{h}:{m:02d}:{sec:05.2f}"

    lines = [header]
    for chunk in chunks:
        # Wrap long chunks
        text = chunk["text"].upper() if len(chunk["text"]) > 20 else chunk["text"]
        wrapped = r"\N".join(textwrap.wrap(text, width=20))
        lines.append(
            f"Dialogue: 0,{fmt(chunk['start'])},{fmt(chunk['end'])},"
            f"Default,,0,0,0,,{{\\an5\\pos({VIDEO_W//2},{int(VIDEO_H*0.80)})}}{wrapped}"
        )

    with open(output_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    return output_path


# ──────────────────────────────────────────────
# FFMPEG COMMAND BUILDERS
# ──────────────────────────────────────────────

def ffmpeg_available() -> bool:
    return shutil.which("ffmpeg") is not None


def check_ffmpeg():
    if not ffmpeg_available():
        raise EnvironmentError(
            "FFmpeg not found!\n"
            "Windows: winget install ffmpeg  OR  choco install ffmpeg\n"
            "Ubuntu:  sudo apt install ffmpeg\n"
            "Mac:     brew install ffmpeg"
        )


def run_ffmpeg(args: List[str], desc: str = "") -> bool:
    """Run an ffmpeg command, log output."""
    cmd = ["ffmpeg", "-y"] + args
    logger.debug(f"[ffmpeg] {desc}: {' '.join(cmd[:6])}...")
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=600,
        )
        if result.returncode != 0:
            logger.error(f"[ffmpeg] Error ({desc}): {result.stderr[-500:]}")
            return False
        return True
    except subprocess.TimeoutExpired:
        logger.error(f"[ffmpeg] Timeout: {desc}")
        return False


# ──────────────────────────────────────────────
# KEN BURNS EFFECT (subtle zoom/pan)
# ──────────────────────────────────────────────

def ken_burns_filter(scene_idx: int, duration: float) -> str:
    """
    Generate an FFmpeg zoompan filter string for Ken Burns effect.
    Alternates between zoom-in and zoom-out.
    """
    frames = int(duration * FPS)
    if scene_idx % 2 == 0:
        # Zoom in
        zoom = f"zoom='min(zoom+0.0015,1.3)'"
        x = f"x='iw/2-(iw/zoom/2)'"
        y = f"y='ih/2-(ih/zoom/2)'"
    else:
        # Zoom out + slight pan
        zoom = f"zoom='if(lte(zoom,1.0),1.3,max(1.0,zoom-0.0015))'"
        x = f"x='iw/2-(iw/zoom/2)+20*sin(on/{frames}*3.14159)'"
        y = f"y='ih/4'"

    return (
        f"zoompan={zoom}:{x}:{y}:"
        f"d={frames}:fps={FPS}:s={VIDEO_W}x{VIDEO_H}"
    )


# ──────────────────────────────────────────────
# VIDEO ASSEMBLY (MOVIEPY — higher level)
# ──────────────────────────────────────────────

class MoviePyAssembler:
    """
    Uses MoviePy for video assembly.
    More Pythonic but slower than pure FFmpeg.
    """

    def assemble(self, scenes_images: List[str], voice_path: str,
                 output_path: str, script_text: str,
                 music_path: Optional[str] = None) -> bool:
        try:
            from moviepy.editor import (
                ImageClip, AudioFileClip, CompositeAudioClip,
                concatenate_videoclips, TextClip, CompositeVideoClip,
            )
            import numpy as np

            check_ffmpeg()

            # Get voice duration
            voice = AudioFileClip(voice_path)
            total_duration = voice.duration + 1.0  # +1s padding
            per_scene = total_duration / len(scenes_images)

            # Build image clips with Ken Burns
            clips = []
            for i, img_path in enumerate(scenes_images):
                dur = min(per_scene, total_duration - i * per_scene)
                dur = max(dur, 1.0)
                clip = (
                    ImageClip(img_path)
                    .set_duration(dur)
                    .resize((VIDEO_W, VIDEO_H))
                )
                # Simple zoom via resize (smoother than zoompan in moviepy)
                if i % 2 == 0:
                    clip = clip.resize(lambda t: 1 + 0.03 * (t / dur))
                clips.append(clip)

            # Concatenate with crossfade
            if TRANSITION == "fade" and len(clips) > 1:
                from moviepy.editor import concatenate_videoclips
                video = concatenate_videoclips(clips, method="compose",
                                               padding=-TRANS_DUR)
            else:
                video = concatenate_videoclips(clips, method="compose")

            # Build audio
            audio_clips = [voice.volumex(VOICE_VOL)]
            if music_path and os.path.exists(music_path):
                music = (
                    AudioFileClip(music_path)
                    .set_duration(total_duration)
                    .volumex(BG_MUSIC_VOL)
                    .audio_fadeout(2.0)
                )
                audio_clips.append(music)
            mixed_audio = CompositeAudioClip(audio_clips)

            # Attach audio
            video = video.set_audio(mixed_audio).set_duration(
                min(video.duration, total_duration))

            # Export
            video.write_videofile(
                output_path,
                fps=FPS,
                codec="libx264",
                audio_codec="aac",
                bitrate=VIDEO_BITRATE,
                audio_bitrate=AUDIO_BITRATE,
                preset="fast",
                logger=None,
            )
            logger.info(f"[moviepy] Video saved: {output_path}")
            return True

        except Exception as e:
            logger.error(f"[moviepy] Assembly failed: {e}")
            return False


# ──────────────────────────────────────────────
# VIDEO ASSEMBLY (PURE FFMPEG — faster, less RAM)
# ──────────────────────────────────────────────

class FFmpegAssembler:
    """
    Pure FFmpeg pipeline — faster and lower memory than MoviePy.
    """

    def assemble(self, scenes_images: List[str], voice_path: str,
                 output_path: str, script_text: str,
                 music_path: Optional[str] = None,
                 tmp_dir: Optional[str] = None) -> bool:
        check_ffmpeg()
        if tmp_dir is None:
            tmp_dir = str(Path(output_path).parent / "_tmp")
        Path(tmp_dir).mkdir(parents=True, exist_ok=True)

        try:
            # 1. Get voice duration
            dur = self._get_duration(voice_path)
            if dur <= 0:
                logger.error("[ffmpeg] Could not get voice duration")
                return False

            per_scene = dur / len(scenes_images)

            # 2. Build concat list for images → video
            concat_file = os.path.join(tmp_dir, "concat.txt")
            with open(concat_file, "w") as f:
                for img in scenes_images:
                    f.write(f"file '{os.path.abspath(img)}'\n")
                    f.write(f"duration {per_scene:.3f}\n")
                # Repeat last image so duration is reached
                f.write(f"file '{os.path.abspath(scenes_images[-1])}'\n")

            # 3. Images → raw video (no audio yet)
            raw_video = os.path.join(tmp_dir, "raw_video.mp4")
            img_args = [
                "-f", "concat",
                "-safe", "0",
                "-i", concat_file,
                "-vf", (
                    f"scale={VIDEO_W}:{VIDEO_H}:force_original_aspect_ratio=increase,"
                    f"crop={VIDEO_W}:{VIDEO_H},"
                    f"format=yuv420p"
                ),
                "-fps_mode", "cfr",
                "-r", str(FPS),
                "-c:v", "libx264",
                "-preset", "fast",
                "-b:v", VIDEO_BITRATE,
                raw_video,
            ]
            if not run_ffmpeg(img_args, "images to video"):
                return False

            # 4. Build subtitle file
            caption_chunks = chunk_text_for_captions(script_text, dur)
            subtitle_path  = os.path.join(tmp_dir, "captions.ass")
            create_ass_subtitles(caption_chunks, subtitle_path)

            # 5. Burn subtitles into video
            burned_video = os.path.join(tmp_dir, "burned_video.mp4")
            # Escape path for Windows
            safe_sub_path = subtitle_path.replace("\\", "/").replace(":", "\\:")
            sub_args = [
                "-i", raw_video,
                "-vf", f"ass='{safe_sub_path}'",
                "-c:v", "libx264",
                "-preset", "fast",
                "-b:v", VIDEO_BITRATE,
                "-c:a", "copy",
                burned_video,
            ]
            if not run_ffmpeg(sub_args, "burn subtitles"):
                # If subtitle burning fails, use raw video
                shutil.copy(raw_video, burned_video)

            # 6. Mix audio (voice + background music)
            if music_path and os.path.exists(music_path):
                mixed_audio = os.path.join(tmp_dir, "mixed_audio.aac")
                audio_args = [
                    "-i", voice_path,
                    "-i", music_path,
                    "-filter_complex", (
                        f"[0:a]volume={VOICE_VOL}[v];"
                        f"[1:a]volume={BG_MUSIC_VOL},atrim=end={dur}[m];"
                        f"[v][m]amix=inputs=2:duration=first:dropout_transition=2[out]"
                    ),
                    "-map", "[out]",
                    "-c:a", "aac",
                    "-b:a", AUDIO_BITRATE,
                    mixed_audio,
                ]
                run_ffmpeg(audio_args, "mix audio")
                audio_input = mixed_audio
            else:
                audio_input = voice_path

            # 7. Combine video + audio, trim to voice duration
            final_args = [
                "-i", burned_video,
                "-i", audio_input,
                "-map", "0:v",
                "-map", "1:a",
                "-c:v", "copy",
                "-c:a", "aac",
                "-b:a", AUDIO_BITRATE,
                "-t", str(dur + 0.5),
                "-movflags", "+faststart",
                output_path,
            ]
            if not run_ffmpeg(final_args, "final mux"):
                return False

            logger.info(f"[ffmpeg] Video assembled: {output_path}")
            return True

        except Exception as e:
            logger.error(f"[ffmpeg] Assembly error: {e}")
            return False
        finally:
            # Clean up tmp files
            try:
                shutil.rmtree(tmp_dir, ignore_errors=True)
            except Exception:
                pass

    def _get_duration(self, media_path: str) -> float:
        """Get media duration in seconds using ffprobe."""
        try:
            result = subprocess.run(
                [
                    "ffprobe", "-v", "quiet",
                    "-show_entries", "format=duration",
                    "-of", "json",
                    media_path,
                ],
                capture_output=True, text=True, timeout=30,
            )
            data = json.loads(result.stdout)
            return float(data["format"]["duration"])
        except Exception:
            return 0.0


# ──────────────────────────────────────────────
# BACKGROUND MUSIC MANAGER
# ──────────────────────────────────────────────

FREE_MUSIC_SOURCES = {
    "freepd": "https://freepd.com",        # Public domain
    "mixkit":  "https://assets.mixkit.co/music/",  # Free license
    "ccmixter": "http://ccmixter.org",     # Creative Commons
}

# Pre-bundled tracks to download and keep in ./assets/music/
BUNDLED_TRACKS = [
    {
        "name": "upbeat_tech.mp3",
        "url": "https://www.chosic.com/wp-content/uploads/2021/04/StoryTime.mp3",
        "description": "Upbeat technology background"
    },
    {
        "name": "calm_ambient.mp3",
        "url": "https://www.chosic.com/wp-content/uploads/2023/10/Positive-Energy-by-Bensound.mp3",
        "description": "Calm ambient background"
    },
]

def get_background_music(category: str = "general") -> Optional[str]:
    """Get a background music file path. Download if not present."""
    MUSIC_DIR.mkdir(parents=True, exist_ok=True)

    # Check local library first
    music_files = list(MUSIC_DIR.glob("*.mp3")) + list(MUSIC_DIR.glob("*.wav"))
    if music_files:
        import random
        return str(random.choice(music_files))

    # Try to download bundled tracks
    for track in BUNDLED_TRACKS:
        dest = MUSIC_DIR / track["name"]
        if not dest.exists():
            try:
                logger.info(f"[music] Downloading {track['name']}...")
                r = requests.get(track["url"], timeout=30, stream=True)
                r.raise_for_status()
                with open(dest, "wb") as f:
                    for chunk in r.iter_content(8192):
                        f.write(chunk)
                logger.info(f"[music] Downloaded: {dest}")
                return str(dest)
            except Exception as e:
                logger.warning(f"[music] Download failed: {e}")

    logger.warning("[music] No background music available — video will be voice-only")
    return None


import requests

# ──────────────────────────────────────────────
# UNIFIED VIDEO ASSEMBLER
# ──────────────────────────────────────────────

class VideoAssembler:
    def __init__(self, use_moviepy: bool = False):
        self.use_moviepy = use_moviepy
        self.ffmpeg_asm = FFmpegAssembler()
        self.moviepy_asm = MoviePyAssembler()

    def assemble(
        self,
        scenes_images: List[str],
        voice_path: str,
        script_text: str,
        run_id: str,
        music_category: str = "general",
    ) -> Optional[str]:
        """
        Full assembly pipeline.
        Returns path to output video or None on failure.
        """
        output_path = str(VIDEOS_DIR / f"{run_id}.mp4")
        music_path  = get_background_music(music_category)
        tmp_dir     = str(VIDEOS_DIR / f"_tmp_{run_id}")

        logger.info(f"[assembler] Starting assembly for run {run_id}")
        logger.info(f"[assembler] Scenes: {len(scenes_images)}, Music: {bool(music_path)}")

        # Filter only existing image files
        valid_scenes = [p for p in scenes_images if os.path.exists(p)]
        if not valid_scenes:
            logger.error("[assembler] No valid scene images found")
            return None

        if self.use_moviepy:
            ok = self.moviepy_asm.assemble(
                valid_scenes, voice_path, output_path, script_text, music_path)
        else:
            ok = self.ffmpeg_asm.assemble(
                valid_scenes, voice_path, output_path, script_text, music_path, tmp_dir)

        if ok and os.path.exists(output_path):
            size_mb = os.path.getsize(output_path) / 1_048_576
            logger.info(f"[assembler] ✅ Video ready: {output_path} ({size_mb:.1f} MB)")
            return output_path

        logger.error("[assembler] Video assembly failed")
        return None

    def get_video_info(self, video_path: str) -> Dict:
        """Get duration and file info."""
        dur = self.ffmpeg_asm._get_duration(video_path)
        size = os.path.getsize(video_path) / 1_048_576
        return {
            "path": video_path,
            "duration": round(dur, 2),
            "size_mb": round(size, 2),
            "resolution": f"{VIDEO_W}x{VIDEO_H}",
        }


if __name__ == "__main__":
    # Test assembly with placeholder images
    from PIL import Image
    import random

    # Create test images
    test_images = []
    for i in range(4):
        path = f"/tmp/test_scene_{i}.jpg"
        img = Image.new("RGB", (1080, 1920),
                        color=(random.randint(20,80),
                               random.randint(20,80),
                               random.randint(80,180)))
        img.save(path)
        test_images.append(path)

    assembler = VideoAssembler()
    # Requires voice file at this path
    out = assembler.assemble(
        test_images,
        voice_path="./output/audio/test_voice.wav",
        script_text="This is a test of the video assembly system.",
        run_id="test_001",
    )
    print(f"Output: {out}")
