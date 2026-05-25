#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 1 || $# -gt 2 ]]; then
  echo "usage: $0 <media_path> [output_dir]" >&2
  exit 1
fi

MEDIA_PATH="$1"
MEDIA_BASENAME="$(basename "$MEDIA_PATH")"
OUTPUT_DIR="${2:-$(dirname "$MEDIA_PATH")}"
OUTPUT_DIR="${OUTPUT_DIR}/${MEDIA_BASENAME}-inspect"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

require_command() {
  local command_name="$1"
  if ! command -v "$command_name" >/dev/null 2>&1; then
    echo "${command_name} is required but not installed or not on PATH." >&2
    exit 1
  fi
}

probe_stream_type() {
  local selector="$1"
  ffprobe \
    -v error \
    -select_streams "$selector" \
    -show_entries stream=codec_type \
    -of csv=p=0 \
    "$MEDIA_PATH" \
    2>/dev/null || true
}

validate_media_probe() {
  local stderr_file
  local error_output

  stderr_file="$(mktemp)"
  if ffprobe \
    -v error \
    -show_entries format=format_name \
    -of default=noprint_wrappers=1:nokey=1 \
    "$MEDIA_PATH" \
    >/dev/null 2>"$stderr_file"; then
    rm -f "$stderr_file"
    return 0
  fi

  error_output="$(<"$stderr_file")"
  rm -f "$stderr_file"

  if [[ -n "$error_output" ]]; then
    echo "$error_output" >&2
  else
    echo "ffprobe failed for: $MEDIA_PATH" >&2
  fi
  exit 1
}

if [[ ! -f "$MEDIA_PATH" ]]; then
  echo "media file not found: $MEDIA_PATH" >&2
  exit 1
fi

require_command ffprobe
require_command python3

validate_media_probe

mkdir -p "$OUTPUT_DIR"

HAS_AUDIO="$(probe_stream_type a:0)"
HAS_VIDEO="$(probe_stream_type v:0)"

TRANSCRIPT_PATH=""
CONTACT_SHEET_PATH=""
FRAMES_DIR=""

if [[ -n "$HAS_AUDIO" ]]; then
  TRANSCRIPT_PATH="$(bash "$SCRIPT_DIR/transcribe_media.sh" "$MEDIA_PATH" "$OUTPUT_DIR")"
fi

if [[ -n "$HAS_VIDEO" ]]; then
  FRAMES_DIR="${OUTPUT_DIR}/frames"
  FRAME_MODE="${FRAME_MODE:-count}" \
  FRAME_COUNT="${FRAME_COUNT:-8}" \
    bash "$SCRIPT_DIR/extract_video_frames.sh" "$MEDIA_PATH" "$FRAMES_DIR" >/dev/null
  CONTACT_SHEET_PATH="$(bash "$SCRIPT_DIR/make_contact_sheet.sh" "$FRAMES_DIR" "${OUTPUT_DIR}/contact-sheet.jpg")"
fi

if [[ -z "$TRANSCRIPT_PATH" && -z "$CONTACT_SHEET_PATH" ]]; then
  echo "no audio or video streams found in: $MEDIA_PATH" >&2
  exit 1
fi

INSPECT_MEDIA_PATH="$MEDIA_PATH" \
INSPECT_OUTPUT_DIR="$OUTPUT_DIR" \
INSPECT_TRANSCRIPT_PATH="$TRANSCRIPT_PATH" \
INSPECT_CONTACT_SHEET_PATH="$CONTACT_SHEET_PATH" \
INSPECT_FRAMES_DIR="$FRAMES_DIR" \
python3 - <<'PY'
import json
import os


def maybe(name):
    value = os.environ.get(name, "")
    return value or None


print(
    json.dumps(
        {
            "media": os.environ["INSPECT_MEDIA_PATH"],
            "output_dir": os.environ["INSPECT_OUTPUT_DIR"],
            "transcript_path": maybe("INSPECT_TRANSCRIPT_PATH"),
            "contact_sheet_path": maybe("INSPECT_CONTACT_SHEET_PATH"),
            "frames_dir": maybe("INSPECT_FRAMES_DIR"),
        }
    )
)
PY
