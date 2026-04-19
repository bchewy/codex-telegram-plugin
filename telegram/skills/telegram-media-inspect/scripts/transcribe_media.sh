#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 1 || $# -gt 2 ]]; then
  echo "usage: $0 <media_path> [output_dir]" >&2
  exit 1
fi

MEDIA_PATH="$1"
OUTPUT_DIR="${2:-$(dirname "$MEDIA_PATH")}"
WHISPER_MODEL="${WHISPER_MODEL:-tiny}"
WHISPER_LANGUAGE="${WHISPER_LANGUAGE:-}"
CACHE_ROOT="${XDG_CACHE_HOME:-$HOME/.cache}/codex-telegram-plugin"
VENV_DIR="${CACHE_ROOT}/whisper-venv"
PYTHON_BIN="${VENV_DIR}/bin/python"
PIP_BIN="${VENV_DIR}/bin/pip"

if [[ ! -f "$MEDIA_PATH" ]]; then
  echo "media file not found: $MEDIA_PATH" >&2
  exit 1
fi

if ! command -v ffmpeg >/dev/null 2>&1; then
  echo "ffmpeg is required but not installed or not on PATH." >&2
  exit 1
fi

if ! command -v python3 >/dev/null 2>&1; then
  echo "python3 is required but not installed or not on PATH." >&2
  exit 1
fi

mkdir -p "$OUTPUT_DIR" "$CACHE_ROOT"

if [[ ! -x "$PYTHON_BIN" ]]; then
  python3 -m venv "$VENV_DIR"
fi

if ! "$PYTHON_BIN" -c "import whisper" >/dev/null 2>&1; then
  "$PIP_BIN" install --disable-pip-version-check openai-whisper
fi

CMD=(
  "$PYTHON_BIN" -m whisper
  "$MEDIA_PATH"
  "--model" "$WHISPER_MODEL"
  "--output_dir" "$OUTPUT_DIR"
)

if [[ -n "$WHISPER_LANGUAGE" ]]; then
  CMD+=("--language" "$WHISPER_LANGUAGE")
fi

"${CMD[@]}"

BASENAME="$(basename "$MEDIA_PATH")"
STEM="${BASENAME%.*}"
TXT_PATH="${OUTPUT_DIR}/${STEM}.txt"

if [[ -f "$TXT_PATH" ]]; then
  echo "$TXT_PATH"
else
  echo "transcription finished, but ${TXT_PATH} was not found" >&2
  exit 1
fi
