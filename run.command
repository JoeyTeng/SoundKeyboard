#!/bin/bash
set -euo pipefail

cd "$(dirname "$0")"

if ! command -v uv >/dev/null 2>&1; then
    echo "uv is required to install and run SoundKeyboard."
    echo "Install it from https://docs.astral.sh/uv/getting-started/installation/"
    exit 1
fi

uv sync --locked
exec uv run --locked python main.py
