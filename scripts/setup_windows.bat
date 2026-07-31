@echo off
:: ============================================================
:: setup_windows.bat — One-click setup for Windows
:: Run this ONCE as Administrator to set up everything.
:: ============================================================

echo ============================================================
echo  YouTube Shorts Bot - Windows Setup
echo ============================================================
echo.

:: Check for Python
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python not found. Install from https://python.org
    echo        Make sure to tick "Add to PATH" during install.
    pause
    exit /b 1
)
echo [OK] Python found

:: Check for pip
pip --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] pip not found. Reinstall Python.
    pause
    exit /b 1
)
echo [OK] pip found

:: Check for FFmpeg
ffmpeg -version >nul 2>&1
if errorlevel 1 (
    echo [WARN] FFmpeg not found.
    echo        Installing via winget...
    winget install --id Gyan.FFmpeg -e --source winget
    if errorlevel 1 (
        echo [ERROR] winget install failed.
        echo        Manual: https://ffmpeg.org/download.html
        echo        Download, extract, add bin/ to PATH.
        pause
        exit /b 1
    )
    echo [OK] FFmpeg installed. You may need to restart this window.
) else (
    echo [OK] FFmpeg found
)

:: Create virtual environment
echo.
echo [1/6] Creating Python virtual environment...
if not exist "venv" (
    python -m venv venv
)
echo [OK] venv created

:: Activate venv
call venv\Scripts\activate.bat

:: Install Python dependencies
echo.
echo [2/6] Installing Python packages (this takes 2-5 minutes)...
pip install --upgrade pip --quiet
pip install -r requirements.txt --quiet
if errorlevel 1 (
    echo [ERROR] pip install failed. Check requirements.txt
    pause
    exit /b 1
)
echo [OK] Packages installed

:: Create directories
echo.
echo [3/6] Creating project directories...
mkdir output\videos output\audio output\images output\thumbnails 2>nul
mkdir data logs config assets\fonts assets\music tools\piper\models 2>nul
echo [OK] Directories created

:: Download Piper TTS
echo.
echo [4/6] Downloading Piper TTS...
if not exist "tools\piper\piper.exe" (
    echo     Downloading Piper binary...
    curl -L -o tools\piper\piper_win.zip ^
        "https://github.com/rhasspy/piper/releases/download/v1.2.0/piper_windows_amd64.zip" ^
        --progress-bar
    if errorlevel 1 (
        echo [WARN] Piper download failed. Download manually:
        echo        https://github.com/rhasspy/piper/releases
        echo        Extract piper.exe to tools\piper\
    ) else (
        powershell -Command "Expand-Archive -Path tools\piper\piper_win.zip -DestinationPath tools\piper\ -Force"
        del tools\piper\piper_win.zip
        echo [OK] Piper extracted
    )
) else (
    echo [OK] Piper already present
)

:: Download Piper voice model
if not exist "tools\piper\models\en_US-amy-medium.onnx" (
    echo     Downloading voice model (Amy, ~60 MB)...
    curl -L -o tools\piper\models\en_US-amy-medium.onnx ^
        "https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/amy/medium/en_US-amy-medium.onnx" ^
        --progress-bar
    curl -L -o tools\piper\models\en_US-amy-medium.onnx.json ^
        "https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/amy/medium/en_US-amy-medium.onnx.json" ^
        --progress-bar
    echo [OK] Voice model downloaded
) else (
    echo [OK] Voice model already present
)

:: Download font
if not exist "assets\fonts\Montserrat-Bold.ttf" (
    echo     Downloading Montserrat font...
    curl -L -o assets\fonts\Montserrat-Bold.ttf ^
        "https://github.com/google/fonts/raw/main/ofl/montserrat/static/Montserrat-Bold.ttf" ^
        --progress-bar
    echo [OK] Font downloaded
) else (
    echo [OK] Font already present
)

:: Copy .env
echo.
echo [5/6] Creating .env file...
if not exist ".env" (
    copy .env.example .env
    echo [OK] .env created from template
    echo.
    echo  *** ACTION REQUIRED ***
    echo  Edit .env and fill in:
    echo    REDDIT_CLIENT_ID     - from reddit.com/prefs/apps
    echo    REDDIT_CLIENT_SECRET - same page
    echo    PIXABAY_API_KEY      - from pixabay.com/api/docs
    echo    GNEWS_API_KEY        - from gnews.io
    echo  These are all FREE to get.
) else (
    echo [OK] .env already exists
)

:: Initialise database
echo.
echo [6/6] Initialising database...
python main.py --init-db
echo [OK] Database ready

:: Optional: Install Ollama
echo.
echo ============================================================
echo  OPTIONAL: Install Ollama for AI script generation
echo  (Better quality than templates. ~4GB download)
echo ============================================================
set /p INSTALL_OLLAMA=Install Ollama now? (y/n): 
if /i "%INSTALL_OLLAMA%"=="y" (
    echo Downloading Ollama installer...
    curl -L -o ollama_setup.exe "https://ollama.com/download/OllamaSetup.exe"
    start /wait ollama_setup.exe
    del ollama_setup.exe
    echo Starting Ollama service...
    start /B ollama serve
    timeout /t 5 /nobreak >nul
    echo Pulling Mistral model (~4GB)...
    ollama pull mistral
    echo [OK] Ollama + Mistral ready
)

echo.
echo ============================================================
echo  SETUP COMPLETE!
echo ============================================================
echo.
echo  Next steps:
echo  1. Edit .env with your API keys (only REDDIT and PIXABAY needed)
echo  2. Authenticate YouTube:
echo        python main.py --auth
echo  3. Test run (no upload):
echo        python main.py --dry-run
echo  4. Run for real:
echo        python main.py
echo  5. Start scheduler (every 6 hours):
echo        python main.py --schedule
echo.
pause
