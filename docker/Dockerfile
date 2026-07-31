# ============================================================
# Dockerfile — YouTube Shorts Bot
# Base: Python 3.11 slim + FFmpeg
# ============================================================
FROM python:3.11-slim

# Prevent interactive prompts
ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

# ── System dependencies ──────────────────────────────────────
RUN apt-get update && apt-get install -y --no-install-recommends \
    # FFmpeg (video assembly)
    ffmpeg \
    # Font rendering
    fonts-liberation \
    fontconfig \
    # Piper TTS dependencies
    wget \
    curl \
    unzip \
    # Build tools for some pip packages
    gcc \
    g++ \
    && rm -rf /var/lib/apt/lists/*

# ── Python dependencies ──────────────────────────────────────
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# ── Download Piper TTS ───────────────────────────────────────
RUN mkdir -p /app/tools/piper/models && \
    wget -q -O /tmp/piper.tar.gz \
    "https://github.com/rhasspy/piper/releases/download/v1.2.0/piper_linux_x86_64.tar.gz" && \
    tar -xzf /tmp/piper.tar.gz -C /app/tools/piper --strip-components=1 && \
    rm /tmp/piper.tar.gz && \
    chmod +x /app/tools/piper/piper

# Download Piper voice model (Amy, medium quality)
RUN wget -q -O /app/tools/piper/models/en_US-amy-medium.onnx \
    "https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/amy/medium/en_US-amy-medium.onnx" && \
    wget -q -O /app/tools/piper/models/en_US-amy-medium.onnx.json \
    "https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/amy/medium/en_US-amy-medium.onnx.json"

# ── Download font ────────────────────────────────────────────
RUN mkdir -p /app/assets/fonts && \
    wget -q -O /app/assets/fonts/Montserrat-Bold.ttf \
    "https://github.com/google/fonts/raw/main/ofl/montserrat/static/Montserrat-Bold.ttf"

# ── Create output directories ────────────────────────────────
RUN mkdir -p \
    /app/output/videos \
    /app/output/audio \
    /app/output/images \
    /app/output/thumbnails \
    /app/data \
    /app/logs \
    /app/config \
    /app/assets/music

# ── Copy source code ─────────────────────────────────────────
COPY . .

# ── Environment ──────────────────────────────────────────────
ENV PIPER_BINARY=/app/tools/piper/piper
ENV PIPER_MODEL=en_US-amy-medium
ENV FONT_PATH=/app/assets/fonts/Montserrat-Bold.ttf
ENV OUTPUT_DIR=/app/output
ENV DATA_DIR=/app/data
ENV DB_PATH=/app/data/bot.db
ENV LOG_LEVEL=INFO

# ── Init database on first run ───────────────────────────────
RUN python main.py --init-db

# ── Healthcheck ──────────────────────────────────────────────
HEALTHCHECK --interval=30m --timeout=10s --start-period=60s \
    CMD python -c "from src.database import init_db, get_session; get_session(init_db()).close(); print('OK')"

CMD ["python", "main.py", "--schedule"]
