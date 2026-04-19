#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 1 || $# -gt 2 ]]; then
  echo "usage: $0 <video_path> [output_dir]" >&2
  exit 1
fi

VIDEO_PATH="$1"
OUTPUT_DIR="${2:-$(dirname "$VIDEO_PATH")/$(basename "${VIDEO_PATH%.*}")-frames}"
FRAME_INTERVAL_SECONDS="${FRAME_INTERVAL_SECONDS:-8}"

if [[ ! -f "$VIDEO_PATH" ]]; then
  echo "video file not found: $VIDEO_PATH" >&2
  exit 1
fi

if ! command -v ffmpeg >/dev/null 2>&1; then
  echo "ffmpeg is required but not installed or not on PATH." >&2
  exit 1
fi

mkdir -p "$OUTPUT_DIR"

ffmpeg -y \
  -i "$VIDEO_PATH" \
  -vf "fps=1/${FRAME_INTERVAL_SECONDS},scale=960:-1" \
  "${OUTPUT_DIR}/frame-%03d.jpg" \
  >/dev/null 2>&1

echo "$OUTPUT_DIR"
