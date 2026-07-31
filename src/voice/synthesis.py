"""
voice/synthesis.py — Free TTS voice generation
Supports: Piper TTS (recommended), Kokoro TTS, Coqui TTS

Comparison:
┌──────────┬────────────┬─────────┬────────────┬──────────────────┐
│ Engine   │ Quality    │ Speed   │ GPU needed │ Setup difficulty │
├──────────┼────────────┼─────────┼────────────┼──────────────────┤
│ Piper    │ ★★★★☆      │ Fast    │ No (CPU)   │ Easy             │
│ Kokoro   │ ★★★★★      │ Medium  │ Optional   │ Medium           │
│ Coqui    │ ★★★☆☆      │ Slow    │ Recommended│ Hard             │
└──────────┴────────────┴─────────┴────────────┴──────────────────┘
RECOMMENDATION: Use Piper for zero-setup, Kokoro for best quality.

PIPER SETUP:
  # Windows:
  1. Download from https://github.com/rhasspy/piper/releases
  2. Extract piper.exe to ./tools/piper/
  3. Download model: en_US-amy-medium.onnx + en_US-amy-medium.onnx.json
     from https://huggingface.co/rhasspy/piper-voices/tree/main/en/en_US/amy/medium
  4. Place in ./tools/piper/models/

  # Linux/WSL:
  wget https://github.com/rhasspy/piper/releases/download/v1.2.0/piper_linux_x86_64.tar.gz
  tar -xzf piper_linux_x86_64.tar.gz

KOKORO SETUP:
  pip install kokoro-onnx soundfile
  # Model downloads automatically on first use
"""
import os, subprocess, tempfile, re
from pathlib import Path
from typing import Optional, List, Dict, Tuple
from loguru import logger
from dotenv import load_dotenv
load_dotenv()

TTS_ENGINE   = os.getenv("TTS_ENGINE", "piper")
PIPER_BINARY = os.getenv("PIPER_BINARY", "./tools/piper/piper")
PIPER_MODEL  = os.getenv("PIPER_MODEL", "en_US-amy-medium")
KOKORO_MODEL = os.getenv("KOKORO_MODEL", "af_heart")
VOICE_SPEED  = float(os.getenv("VOICE_SPEED", "1.0"))


# ──────────────────────────────────────────────
# TEXT PREPROCESSING
# ──────────────────────────────────────────────

def clean_for_tts(text: str) -> str:
    """
    Clean script text so TTS sounds natural.
    - Remove markdown formatting
    - Expand abbreviations
    - Handle numbers
    - Remove stage directions
    """
    # Remove markdown
    text = re.sub(r'\*{1,3}(.*?)\*{1,3}', r'\1', text)
    text = re.sub(r'#{1,6}\s+', '', text)
    text = re.sub(r'\[.*?\]', '', text)
    text = re.sub(r'\(.*?\)', '', text)

    # Expand common abbreviations
    replacements = {
        r'\bDr\.': 'Doctor',
        r'\bMr\.': 'Mister',
        r'\bMrs\.': 'Missus',
        r'\bvs\.': 'versus',
        r'\betc\.': 'etcetera',
        r'\be\.g\.': 'for example',
        r'\bi\.e\.': 'that is',
        r'\bNASA\b': 'NASA',
        r'\bAI\b': 'A I',
        r'\bDNA\b': 'D N A',
        r'\bUSA\b': 'U S A',
    }
    for pattern, replacement in replacements.items():
        text = re.sub(pattern, replacement, text)

    # Handle numbers with suffixes
    text = re.sub(r'(\d+)x\b', r'\1 times', text)
    text = re.sub(r'(\d+)k\b', lambda m: f"{int(m.group(1))} thousand", text)
    text = re.sub(r'(\d+)M\b', lambda m: f"{int(m.group(1))} million", text)

    # Clean emoji and symbols
    text = re.sub(r'[😀-🙏🌀-🗿🚀-🛿🌈💫🔥⚡🎯🎭🎬]+', '', text)
    text = re.sub(r'[#@&*|<>{}]+', '', text)
    text = re.sub(r'\.{2,}', '...', text)

    # Normalise whitespace
    text = re.sub(r'\s+', ' ', text).strip()
    return text


def split_into_sentences(text: str) -> List[str]:
    """Split text into individual sentences for subtitle sync."""
    sentences = re.split(r'(?<=[.!?])\s+', text)
    return [s.strip() for s in sentences if s.strip()]


# ──────────────────────────────────────────────
# PIPER TTS (RECOMMENDED — CPU only, fast)
# ──────────────────────────────────────────────

class PiperTTS:
    """
    Piper is a fast, local neural TTS.
    CPU-only, runs on any machine, good quality voices.
    """

    def __init__(self):
        self.binary = Path(PIPER_BINARY)
        model_dir = self.binary.parent / "models"
        self.model = str(model_dir / f"{PIPER_MODEL}.onnx")
        self.config = str(model_dir / f"{PIPER_MODEL}.onnx.json")

    def is_available(self) -> bool:
        return self.binary.exists() or self._find_piper_in_path()

    def _find_piper_in_path(self) -> bool:
        import shutil
        return shutil.which("piper") is not None

    def synthesise(self, text: str, output_path: str,
                   speed: float = VOICE_SPEED) -> bool:
        """
        Convert text to WAV audio using Piper TTS.
        Args:
            text: Clean voiceover text
            output_path: Path to save .wav file
            speed: Speech rate (0.5 = slow, 1.0 = normal, 1.5 = fast)
        """
        text = clean_for_tts(text)
        os.makedirs(os.path.dirname(output_path), exist_ok=True)

        # Find piper binary
        piper_cmd = str(self.binary) if self.binary.exists() else "piper"

        cmd = [
            piper_cmd,
            "--model", self.model,
            "--config", self.config,
            "--output_file", output_path,
            "--length_scale", str(1.0 / speed),  # piper uses inverse of speed
        ]

        try:
            result = subprocess.run(
                cmd,
                input=text.encode("utf-8"),
                capture_output=True,
                timeout=120,
                check=True,
            )
            if os.path.exists(output_path) and os.path.getsize(output_path) > 0:
                logger.info(f"[piper] Audio saved to {output_path}")
                return True
            logger.error("[piper] Output file empty or missing")
            return False
        except subprocess.CalledProcessError as e:
            logger.error(f"[piper] Error: {e.stderr.decode()}")
            return False
        except FileNotFoundError:
            logger.error(f"[piper] Binary not found: {piper_cmd}")
            return False

    def get_duration(self, wav_path: str) -> float:
        """Get duration of WAV file in seconds."""
        try:
            import soundfile as sf
            data, samplerate = sf.read(wav_path)
            return len(data) / samplerate
        except Exception:
            # Fallback: estimate from word count
            return 0.0


# ──────────────────────────────────────────────
# KOKORO TTS (BEST QUALITY — can use CPU)
# pip install kokoro-onnx
# ──────────────────────────────────────────────

class KokoroTTS:
    """
    Kokoro is the highest-quality free TTS.
    Uses ONNX for CPU inference (no GPU required).
    Multiple voices available.

    Available voices: af_heart, af_bella, af_sarah, af_sky,
                      am_adam, am_michael, bf_emma, bm_george
    """

    def __init__(self):
        self.voice = KOKORO_MODEL

    def is_available(self) -> bool:
        try:
            import kokoro_onnx
            return True
        except ImportError:
            return False

    def synthesise(self, text: str, output_path: str,
                   speed: float = VOICE_SPEED) -> bool:
        if not self.is_available():
            logger.warning("[kokoro] kokoro-onnx not installed: pip install kokoro-onnx")
            return False

        text = clean_for_tts(text)
        os.makedirs(os.path.dirname(output_path), exist_ok=True)

        try:
            from kokoro_onnx import Kokoro
            import soundfile as sf
            import numpy as np

            logger.info("[kokoro] Synthesising speech...")
            kokoro = Kokoro("kokoro-v0_19.onnx", "voices.bin")

            # Generate in chunks to handle long texts
            chunks = self._split_chunks(text, max_chars=300)
            all_samples = []
            sample_rate = 24000

            for chunk in chunks:
                if not chunk.strip():
                    continue
                samples, sr = kokoro.create(
                    chunk,
                    voice=self.voice,
                    speed=speed,
                    lang="en-us",
                )
                all_samples.append(samples)
                sample_rate = sr

            if not all_samples:
                return False

            combined = np.concatenate(all_samples)
            sf.write(output_path, combined, sample_rate)
            logger.info(f"[kokoro] Audio saved to {output_path}")
            return True

        except Exception as e:
            logger.error(f"[kokoro] Error: {e}")
            return False

    def _split_chunks(self, text: str, max_chars: int = 300) -> List[str]:
        """Split text at sentence boundaries for chunk processing."""
        sentences = split_into_sentences(text)
        chunks = []
        current = ""
        for s in sentences:
            if len(current) + len(s) < max_chars:
                current += " " + s
            else:
                if current:
                    chunks.append(current.strip())
                current = s
        if current:
            chunks.append(current.strip())
        return chunks


# ──────────────────────────────────────────────
# COQUI TTS (pip install TTS — large download)
# Slower, needs more RAM, but many voices
# ──────────────────────────────────────────────

class CoquiTTS:
    """
    Coqui TTS — heavyweight but powerful.
    Best used when GPU is available (RTX 2060+ for real-time).
    CPU works but is 5-10x slower than real-time.

    Models: tts_models/en/ljspeech/tacotron2-DDC (fastest CPU)
            tts_models/en/vctk/vits (multi-speaker, CPU ok)
    """

    def is_available(self) -> bool:
        try:
            from TTS.api import TTS
            return True
        except ImportError:
            return False

    def synthesise(self, text: str, output_path: str,
                   speed: float = VOICE_SPEED) -> bool:
        if not self.is_available():
            logger.warning("[coqui] TTS package not installed: pip install TTS")
            return False

        text = clean_for_tts(text)
        os.makedirs(os.path.dirname(output_path), exist_ok=True)

        try:
            from TTS.api import TTS as CoquiAPI
            # CPU-friendly model
            tts = CoquiAPI(model_name="tts_models/en/ljspeech/tacotron2-DDC",
                           gpu=False)
            tts.tts_to_file(text=text, file_path=output_path)
            logger.info(f"[coqui] Audio saved to {output_path}")
            return True
        except Exception as e:
            logger.error(f"[coqui] Error: {e}")
            return False


# ──────────────────────────────────────────────
# UNIFIED VOICE GENERATOR
# ──────────────────────────────────────────────

class VoiceGenerator:
    """
    Tries each TTS engine in order of quality/availability.
    """

    def __init__(self):
        engine_name = TTS_ENGINE.lower()
        if engine_name == "piper":
            self.engines = [PiperTTS(), KokoroTTS(), CoquiTTS()]
        elif engine_name == "kokoro":
            self.engines = [KokoroTTS(), PiperTTS(), CoquiTTS()]
        elif engine_name == "coqui":
            self.engines = [CoquiTTS(), PiperTTS(), KokoroTTS()]
        else:
            self.engines = [PiperTTS(), KokoroTTS(), CoquiTTS()]

    def generate(self, text: str, output_path: str,
                 speed: float = VOICE_SPEED) -> Tuple[bool, str]:
        """
        Generate voice audio.
        Returns (success: bool, engine_used: str)
        """
        for engine in self.engines:
            if engine.is_available():
                logger.info(f"[voice] Trying engine: {engine.__class__.__name__}")
                success = engine.synthesise(text, output_path, speed)
                if success:
                    return True, engine.__class__.__name__
                logger.warning(f"[voice] {engine.__class__.__name__} failed, trying next")

        # Last resort: silence file
        logger.error("[voice] ALL TTS engines failed — generating silence")
        self._generate_silence(output_path, duration=60.0)
        return False, "silence"

    def _generate_silence(self, output_path: str, duration: float = 60.0):
        """Generate a silent WAV file as last resort fallback."""
        import wave, struct, math
        sample_rate = 24000
        n_samples = int(sample_rate * duration)
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        with wave.open(output_path, 'w') as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(sample_rate)
            wf.writeframes(struct.pack('<' + 'h' * n_samples, *([0] * n_samples)))

    def generate_word_timestamps(self, audio_path: str,
                                  script_text: str) -> List[Dict]:
        """
        Estimate word timestamps for caption sync.
        Uses audio duration / word count for uniform distribution.
        For precise sync, use Whisper transcription.
        """
        try:
            import soundfile as sf
            data, sr = sf.read(audio_path)
            total_dur = len(data) / sr
        except Exception:
            total_dur = len(script_text.split()) / WPS

        words = script_text.split()
        wps = len(words) / total_dur if total_dur > 0 else 2.33
        timestamps = []
        for i, word in enumerate(words):
            timestamps.append({
                "word": word,
                "start": round(i / wps, 3),
                "end": round((i + 1) / wps, 3),
            })
        return timestamps


# For import
from typing import Dict, Tuple

WPS = 2.33

if __name__ == "__main__":
    gen = VoiceGenerator()
    test_text = (
        "Did you know that a single teaspoon of honey represents "
        "the life work of twelve bees? Next time you eat honey, "
        "you're tasting something truly extraordinary. "
        "Follow for more facts that will blow your mind."
    )
    success, engine = gen.generate(
        test_text,
        "./output/audio/test_voice.wav"
    )
    print(f"Success: {success}, Engine: {engine}")
