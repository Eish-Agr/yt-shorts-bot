#!/usr/bin/env bash
# ============================================================
# setup_linux.sh — One-command setup for Ubuntu/Debian/WSL2
# Usage: bash scripts/setup_linux.sh
# ============================================================
set -e
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
ok()   { echo -e "${GREEN}[OK]${NC} $1"; }
warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
err()  { echo -e "${RED}[ERROR]${NC} $1"; exit 1; }
step() { echo -e "\n${YELLOW}[$1]${NC} $2"; }

echo "============================================================"
echo " YouTube Shorts Bot — Linux/WSL2 Setup"
echo "============================================================"

# ── System packages ───────────────────────────────────────────
step "1/7" "Installing system packages"
sudo apt-get update -qq
sudo apt-get install -y --no-install-recommends \
    python3 python3-pip python3-venv \
    ffmpeg \
    wget curl unzip git \
    fonts-liberation fontconfig \
    libasound2-dev
ok "System packages installed"

# ── Virtual environment ───────────────────────────────────────
step "2/7" "Setting up Python virtual environment"
if [ ! -d "venv" ]; then
    python3 -m venv venv
fi
source venv/bin/activate
pip install --upgrade pip --quiet
ok "venv activated"

# ── Python packages ───────────────────────────────────────────
step "3/7" "Installing Python packages"
pip install -r requirements.txt --quiet
ok "Python packages installed"

# ── Project directories ───────────────────────────────────────
step "4/7" "Creating directories"
mkdir -p output/{videos,audio,images,thumbnails} \
         data logs config assets/{fonts,music} \
         tools/piper/models
ok "Directories created"

# ── Piper TTS ─────────────────────────────────────────────────
step "5/7" "Downloading Piper TTS"
ARCH=$(uname -m)
if [ "$ARCH" = "x86_64" ]; then
    PIPER_URL="https://github.com/rhasspy/piper/releases/download/v1.2.0/piper_amd64.tar.gz"
elif [ "$ARCH" = "aarch64" ]; then
    PIPER_URL="https://github.com/rhasspy/piper/releases/download/v1.2.0/piper_arm64.tar.gz"
else
    warn "Unknown arch $ARCH — skipping Piper download. Kokoro will be used as fallback."
    PIPER_URL=""
fi

if [ -n "$PIPER_URL" ] && [ ! -f "tools/piper/piper" ]; then
    wget -q --show-progress -O /tmp/piper.tar.gz "$PIPER_URL"
    tar -xzf /tmp/piper.tar.gz -C tools/piper/ --strip-components=1
    chmod +x tools/piper/piper
    rm /tmp/piper.tar.gz
    ok "Piper binary ready"
else
    ok "Piper already present"
fi

# Download Amy voice model
if [ ! -f "tools/piper/models/en_US-amy-medium.onnx" ]; then
    echo "  Downloading Amy voice model (~60 MB)..."
    BASE="https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/amy/medium"
    wget -q --show-progress -O tools/piper/models/en_US-amy-medium.onnx "$BASE/en_US-amy-medium.onnx"
    wget -q -O tools/piper/models/en_US-amy-medium.onnx.json "$BASE/en_US-amy-medium.onnx.json"
    ok "Voice model downloaded"
else
    ok "Voice model already present"
fi

# ── Font ──────────────────────────────────────────────────────
if [ ! -f "assets/fonts/Montserrat-Bold.ttf" ]; then
    wget -q -O assets/fonts/Montserrat-Bold.ttf \
        "https://raw.githubusercontent.com/JulietaUla/Montserrat/master/fonts/ttf/Montserrat-Bold.ttf"
    ok "Font downloaded"
else
    ok "Font already present"
fi

# ── .env file ─────────────────────────────────────────────────
step "6/7" "Setting up .env"
if [ ! -f ".env" ]; then
    cp .env.example .env
    ok ".env created from template"
    echo ""
    warn "ACTION REQUIRED: Edit .env and fill in:"
    echo "   REDDIT_CLIENT_ID     → reddit.com/prefs/apps"
    echo "   REDDIT_CLIENT_SECRET → same page"
    echo "   PIXABAY_API_KEY      → pixabay.com/api/docs"
    echo "   GNEWS_API_KEY        → gnews.io (free)"
else
    ok ".env already exists"
fi

# ── Database ──────────────────────────────────────────────────
step "7/7" "Initialising database"
python main.py --init-db
ok "Database initialised"

# ── Optional: Ollama ─────────────────────────────────────────
echo ""
echo "============================================================"
echo " OPTIONAL: Install Ollama for AI script generation"
echo " Better quality than templates. Requires ~4 GB disk."
echo "============================================================"
read -p "Install Ollama now? (y/n): " INSTALL_OLLAMA
if [ "$INSTALL_OLLAMA" = "y" ] || [ "$INSTALL_OLLAMA" = "Y" ]; then
    curl -fsSL https://ollama.com/install.sh | sh
    ollama serve &
    sleep 5
    ollama pull mistral
    ok "Ollama + Mistral ready"
fi

echo ""
echo "============================================================"
echo " SETUP COMPLETE!"
echo "============================================================"
echo ""
echo " Activate venv first in every new terminal:"
echo "   source venv/bin/activate"
echo ""
echo " Next steps:"
echo "   1. Edit .env with your free API keys"
echo "   2. Authenticate YouTube:    python main.py --auth"
echo "   3. Test (no upload):        python main.py --dry-run"
echo "   4. Run for real:            python main.py"
echo "   5. Start scheduler:         python main.py --schedule"
echo ""
