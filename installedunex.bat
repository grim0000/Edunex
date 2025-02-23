@echo off
echo Checking for pip...
py -m pip --version >nul 2>&1
if %errorlevel% neq 0 (
    echo pip is not installed or Python is not found. Please install Python and pip first.
    exit /b 1
)

echo Installing required Python packages...
py -m pip install Flask firebase-admin gtts aiohttp requests werkzeug huggingface_hub
if %errorlevel% neq 0 (
    echo Failed to install some packages. Check your internet connection or pip configuration.
    exit /b 1
)

echo Installation complete.