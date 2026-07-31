# YouTube Shorts Automation Bot

Fully automated pipeline that finds trending topics, generates a script with AI,
creates a voiceover, downloads visuals, assembles a 1080×1920 Short, generates a
thumbnail, and uploads it to YouTube — all for ₹0.

---

## What It Does (9 Stages)

```
Trends → Rank → Script → Voice → Visuals → Video → Thumbnail → Upload → Analytics
```

| Stage | Tool | Free? |
|-------|------|-------|
| Trend discovery | Google Trends, Reddit, HN, RSS, YouTube API | ✅ |
| Topic ranking | Custom scoring formula (Python) | ✅ |
| Script generation | Ollama + Mistral (local LLM) or template | ✅ |
| Voice synthesis | Piper TTS or Kokoro TTS (local, CPU) | ✅ |
| Visual generation | Pixabay / Pexels / Pexels + SD (local) | ✅ |
| Video assembly | FFmpeg + MoviePy | ✅ |
| Thumbnail | Pillow | ✅ |
| YouTube upload | YouTube Data API v3 (free quota) | ✅ |
| Monitoring | Loguru + SQLite | ✅ |

---

## Prerequisites

| Tool | Min version | Check |
|------|------------|-------|
| Python | 3.10+ | `python --version` |
| FFmpeg | 5.0+ | `ffmpeg -version` |
| Git | any | `git --version` |
| 4 GB disk free | — | for models + output |

**Windows-only:** FFmpeg must be on PATH.
Install: `winget install ffmpeg` or download from ffmpeg.org/download.html

---

## Part A — First-Time Setup

### Windows (Recommended for beginners)

```bat
:: 1. Clone / download the project
git clone <repo_url> yt_shorts_bot
cd yt_shorts_bot

:: 2. Run the automated setup (run as Administrator)
scripts\setup_windows.bat
```

The script installs everything automatically:
- Python venv + all packages
- FFmpeg (via winget)
- Piper TTS binary + Amy voice model
- Montserrat font
- Creates `.env` from template
- Initialises the SQLite database

### Linux / WSL2

```bash
git clone <repo_url> yt_shorts_bot
cd yt_shorts_bot
bash scripts/setup_linux.sh
```

### Manual Setup (if scripts don't work)

```bash
# 1. Create venv
python -m venv venv
source venv/bin/activate          # Linux/Mac
venv\Scripts\activate             # Windows

# 2. Install packages
pip install -r requirements.txt

# 3. Create directories
mkdir -p output/{videos,audio,images,thumbnails} data logs config assets/{fonts,music} tools/piper/models

# 4. Download Piper TTS
# Windows: https://github.com/rhasspy/piper/releases → piper_windows_amd64.zip
# Linux:   wget https://github.com/rhasspy/piper/releases/download/v1.2.0/piper_linux_x86_64.tar.gz
#          tar -xzf piper_linux_x86_64.tar.gz -C tools/piper/

# 5. Download Amy voice model (~60 MB)
# https://huggingface.co/rhasspy/piper-voices/tree/main/en/en_US/amy/medium
# Save en_US-amy-medium.onnx + en_US-amy-medium.onnx.json to tools/piper/models/

# 6. Download Montserrat font
# https://fonts.google.com/specimen/Montserrat → Download
# Copy Montserrat-Bold.ttf to assets/fonts/

# 7. Copy env template
cp .env.example .env

# 8. Init DB
python main.py --init-db
```

---

## Part B — Get Free API Keys (15 minutes total)

You need at minimum 2 keys. All are free.

### 1. Reddit API (required for best trend data)
1. Go to https://www.reddit.com/prefs/apps
2. Click "Create App" at the bottom
3. Name: `YTShortsBot`, type: **script**, redirect: `http://localhost`
4. Copy **client_id** (under the app name) and **client_secret**
5. Paste into `.env`:
   ```
   REDDIT_CLIENT_ID=your_id_here
   REDDIT_CLIENT_SECRET=your_secret_here
   ```

### 2. Pixabay API (required for stock images)
1. Sign up free at https://pixabay.com/accounts/register/
2. Go to https://pixabay.com/api/docs/
3. Your API key is shown at the top when logged in
4. Paste into `.env`:
   ```
   PIXABAY_API_KEY=your_key_here
   ```

### 3. GNews API (optional, 100 req/day free)
1. Sign up at https://gnews.io/
2. Copy your key to `.env`:
   ```
   GNEWS_API_KEY=your_key_here
   ```

### 4. Pexels API (optional, 200 req/hour free)
1. Sign up at https://www.pexels.com/api/
2. Copy your key to `.env`:
   ```
   PEXELS_API_KEY=your_key_here
   ```

---

## Part C — YouTube Authentication (10 minutes, one-time)

This is the most important step. Do it once and the token refreshes automatically.

### Step 1: Create a Google Cloud project
1. Go to https://console.cloud.google.com
2. Click "New Project" → name it `YT Shorts Bot` → Create
3. Click "Enable APIs and Services"
4. Search for **YouTube Data API v3** → Enable

### Step 2: Create OAuth credentials
1. Go to "Credentials" → "Create Credentials" → "OAuth 2.0 Client IDs"
2. Application type: **Desktop app**
3. Name: `YT Shorts Bot`
4. Click Create → Download JSON
5. Rename the file to `client_secrets.json`
6. Place it in the `config/` folder

### Step 3: Add yourself as a test user
1. Go to "OAuth consent screen"
2. Scroll down to "Test users" → Add your Google account email

### Step 4: Authenticate
```bash
# Activate venv first
source venv/bin/activate   # Linux
venv\Scripts\activate      # Windows

python main.py --auth
```
A browser window opens → sign in with your YouTube account → Allow.
Token is saved to `config/youtube_token.json` automatically.
You never need to do this again (token auto-refreshes).

---

## Part D — Install Ollama for AI Scripts (optional but recommended)

Without Ollama, the bot uses template-based scripts. With Ollama you get
genuinely unique, AI-written scripts every time.

```bash
# Linux / WSL2
curl -fsSL https://ollama.com/install.sh | sh
ollama serve &            # start in background
ollama pull mistral       # ~4 GB download

# Windows
# Download OllamaSetup.exe from https://ollama.com/download
# Install it, then in a terminal:
ollama pull mistral
```

Verify it's working:
```bash
ollama run mistral "Write a 3-sentence YouTube hook about space."
```

---

## Part E — Test the Pipeline

### Test 1: Dry run (no upload, all stages)
```bash
source venv/bin/activate
python main.py --dry-run
```
Expected output:
```
09:14:22 | INFO    | [stage1] Collected 84 raw trend items
09:14:23 | INFO    | [stage2] Selected topic: 'Scientists discover deep sea creature'
09:14:24 | INFO    | [stage3] Script: 142 words ≈ 61s (model: mistral)
09:14:28 | INFO    | [stage4] Audio: ./output/audio/run_xxx.wav (engine: PiperTTS)
09:14:35 | INFO    | [stage5] 8 images ready
09:14:55 | INFO    | [stage6] Video: ./output/videos/run_xxx.mp4 (61s, 38.2 MB)
09:14:56 | INFO    | [stage7] Thumbnail: ./output/thumbnails/run_xxx_thumb.jpg
09:14:56 | INFO    | [stage8] DRY RUN — skipping YouTube upload
✅ Done! Topic: Scientists discover deep sea creature
```

Check the output folder — you should see a real `.mp4` and `.jpg`.

### Test 2: Specific component tests
```bash
# Test only TTS
python -m src.voice.synthesis

# Test only trend discovery
python -m src.trend.discovery

# Test only script generation
python -m src.script.generator

# Test only thumbnail
python -m src.thumbnail.generator
```

### Test 3: Full real run
```bash
python main.py
```
Watch the logs. The video will appear at `https://youtu.be/<id>`.

---

## Part F — Run on a Schedule

### Option 1: Built-in scheduler (simplest)
```bash
python main.py --schedule
```
Runs every 6 hours (configurable via `SCHEDULE_HOURS` in `.env`), max 4 videos/day.

Keep it running: use a terminal multiplexer or background process.
```bash
# Linux: run in background, keep after logout
nohup python main.py --schedule >> logs/scheduler.log 2>&1 &
echo $! > logs/scheduler.pid
```

### Option 2: Windows Task Scheduler
1. Open Task Scheduler → Create Basic Task
2. Name: `YT Shorts Bot`
3. Trigger: Daily, repeat every 6 hours
4. Action: Start a Program
   - Program: `C:\path\to\yt_shorts_bot\venv\Scripts\python.exe`
   - Arguments: `main.py`
   - Start in: `C:\path\to\yt_shorts_bot`
5. Finish

### Option 3: Linux cron
```bash
crontab -e
# Add this line (runs at 6am, 12pm, 6pm, midnight UTC):
0 0,6,12,18 * * * cd /path/to/yt_shorts_bot && venv/bin/python main.py >> logs/cron.log 2>&1
```

### Option 4: Docker (most reliable)
```bash
cd docker

# First time: build and start
docker compose up -d --build

# Pull Mistral into Ollama container
docker compose exec ollama ollama pull mistral

# Copy your YouTube credentials
cp ../config/client_secrets.json ../config/
cp ../config/youtube_token.json ../config/     # if already authed

# Follow logs
docker compose logs -f bot

# Stop
docker compose down
```

### Option 5: n8n workflow
```bash
# Start n8n (standalone)
npm install -g n8n
n8n start

# Open http://localhost:5678
# Import: Settings → Import → select n8n/workflow.json
# Activate the workflow
```

---

## Part G — Configuration Reference

Edit `.env` to customise behaviour:

```ini
# How often to run (hours)
SCHEDULE_HOURS=6

# Max videos per day (YouTube free quota: 6/day)
MAX_VIDEOS_PER_DAY=4

# Script duration (30, 60, or 90 seconds)
VIDEO_DURATION=60

# TTS engine: piper (fast) or kokoro (best quality)
TTS_ENGINE=piper

# Visual strategy: mixed (recommended), stock, stable_diffusion
VISUAL_ENGINE=mixed

# Upload privacy: public, private, unlisted
YT_PRIVACY=public

# Scoring weights (must sum to 1.0)
WEIGHT_SEARCH_VOLUME=0.30
WEIGHT_RECENCY=0.25
WEIGHT_VIRALITY=0.25
WEIGHT_COMPETITION=0.20
```

---

## Part H — Project File Structure

```
yt_shorts_bot/
├── main.py                        ← ENTRY POINT — run this
├── requirements.txt
├── .env.example                   ← copy to .env
│
├── src/
│   ├── database.py                ← SQLite schema (Topics, Videos, Uploads…)
│   ├── trend/
│   │   └── discovery.py           ← Google Trends, Reddit, HN, RSS, YouTube, GitHub, GNews
│   ├── ranking/
│   │   └── engine.py              ← Scoring formula + topic selector
│   ├── script/
│   │   └── generator.py           ← Ollama LLM + template fallback
│   ├── voice/
│   │   └── synthesis.py           ← Piper TTS + Kokoro TTS + Coqui TTS
│   ├── visual/
│   │   └── generator.py           ← Pixabay + Pexels + Unsplash + Stable Diffusion
│   ├── video/
│   │   └── assembler.py           ← FFmpeg + MoviePy → 1080×1920 .mp4
│   ├── thumbnail/
│   │   └── generator.py           ← Pillow → 1280×720 .jpg
│   ├── upload/
│   │   └── youtube.py             ← YouTube Data API v3 uploader
│   ├── monitoring/
│   │   └── logger.py              ← Logging, retry, alerting, dedup
│   └── growth/
│       └── optimizer.py           ← A/B testing, clustering, trend prediction
│
├── n8n/
│   └── workflow.json              ← Import this into n8n
│
├── docker/
│   ├── Dockerfile
│   └── docker-compose.yml         ← Bot + Ollama + n8n
│
├── scripts/
│   ├── setup_windows.bat          ← One-click Windows setup
│   └── setup_linux.sh             ← One-click Linux setup
│
├── config/                        ← Put client_secrets.json here
├── data/                          ← SQLite DB lives here
├── logs/                          ← Log files (auto-created)
├── output/
│   ├── videos/                    ← Final .mp4 files
│   ├── audio/                     ← TTS .wav files
│   ├── images/                    ← Downloaded/generated images
│   └── thumbnails/                ← Thumbnail .jpg files
├── assets/
│   ├── fonts/                     ← Montserrat-Bold.ttf
│   └── music/                     ← Background music .mp3 files
└── tools/
    └── piper/
        ├── piper(.exe)
        └── models/                ← .onnx voice models
```

---

## Part I — Common Errors and Fixes

| Error | Cause | Fix |
|-------|-------|-----|
| `FFmpeg not found` | FFmpeg not on PATH | `winget install ffmpeg` then restart terminal |
| `Piper binary not found` | Wrong path | Check `PIPER_BINARY` in `.env` |
| `No module named 'praw'` | venv not activated | `source venv/bin/activate` |
| `client_secrets.json not found` | Missing Google creds | Follow Part C above |
| `403 Forbidden` (YouTube) | Quota exceeded | Wait 24h or reduce `MAX_VIDEOS_PER_DAY` |
| `All top topics recently used` | 14-day cooldown | Add more subreddits to `.env` |
| `Ollama connection refused` | Ollama not running | Run `ollama serve` in a separate terminal |
| Empty video / no audio | TTS failed | Run `python -m src.voice.synthesis` to debug |
| `Token expired` | YouTube token stale | Run `python main.py --auth` again |

---

## Part J — Getting Background Music

The bot will download tracks automatically on first run. To add your own:

1. Download free music from https://freepd.com (public domain) or
   https://www.chosic.com/free-music/all/
2. Place `.mp3` files in `assets/music/`
3. Bot picks randomly from this folder

---

## Part K — View Stats

```bash
python main.py --stats
```
Output:
```json
{
  "last_7_days": {
    "runs_total": 14,
    "runs_ok": 13,
    "runs_failed": 1,
    "success_rate": "93%",
    "videos_uploaded": 13
  }
}
```
