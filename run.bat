@echo off
setlocal
pushd "%~dp0"

where uv >nul 2>nul
if errorlevel 1 (
    echo uv is required to install and run SoundKeyboard.
    echo Install it from https://docs.astral.sh/uv/getting-started/installation/
    popd
    pause
    exit /b 1
)

uv sync --locked
if errorlevel 1 (
    echo Dependency installation failed.
    popd
    pause
    exit /b 1
)

uv run --locked python main.py
set "result=%errorlevel%"
popd
exit /b %result%
