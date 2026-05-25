#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 1 || $# -gt 2 ]]; then
  echo "usage: $0 <video_path> [output_dir]" >&2
  exit 1
fi

VIDEO_PATH="$1"
VIDEO_BASENAME="$(basename "$VIDEO_PATH")"
OUTPUT_DIR="${2:-$(dirname "$VIDEO_PATH")/${VIDEO_BASENAME}-frames}"
FRAME_INTERVAL_SECONDS="${FRAME_INTERVAL_SECONDS:-8}"
FRAME_MODE="${FRAME_MODE:-interval}"
FRAME_COUNT="${FRAME_COUNT:-8}"

require_command() {
  local command_name="$1"
  if ! command -v "$command_name" >/dev/null 2>&1; then
    echo "${command_name} is required but not installed or not on PATH." >&2
    exit 1
  fi
}

require_positive_number() {
  local value="$1"
  local label="$2"

  if [[ ! "$value" =~ ^[0-9]+([.][0-9]+)?$ ]]; then
    echo "${label} must be a positive number: ${value}" >&2
    exit 1
  fi

  if ! awk -v value="$value" 'BEGIN { exit !(value > 0) }'; then
    echo "${label} must be greater than 0: ${value}" >&2
    exit 1
  fi
}

require_positive_integer() {
  local value="$1"
  local label="$2"

  if [[ ! "$value" =~ ^[1-9][0-9]*$ ]]; then
    echo "${label} must be a positive integer: ${value}" >&2
    exit 1
  fi
}

calc_even_interval() {
  local duration="$1"
  local frame_count="$2"

  awk -v duration="$duration" -v frame_count="$frame_count" '
    BEGIN {
      if (duration <= 0 || frame_count <= 0) {
        exit 1
      }
      printf "%.6f", duration / frame_count
    }
  '
}

clear_existing_frames() {
  local existing_frames=()

  shopt -s nullglob
  existing_frames=("$OUTPUT_DIR"/frame-*.jpg)
  shopt -u nullglob

  if [[ ${#existing_frames[@]} -gt 0 ]]; then
    rm -f "${existing_frames[@]}"
  fi
}

has_output_frames() {
  local existing_frames=()

  shopt -s nullglob
  existing_frames=("$OUTPUT_DIR"/frame-*.jpg)
  shopt -u nullglob

  [[ ${#existing_frames[@]} -gt 0 ]]
}

run_ffmpeg() {
  local suppress_errors="${1:-0}"
  local stderr_file
  local error_output

  stderr_file="$(mktemp)"
  if "${CMD[@]}" >/dev/null 2>"$stderr_file"; then
    rm -f "$stderr_file"
    return 0
  fi

  error_output="$(<"$stderr_file")"
  rm -f "$stderr_file"

  if [[ "$suppress_errors" != "1" ]]; then
    if [[ -n "$error_output" ]]; then
      echo "$error_output" >&2
    else
      echo "ffmpeg frame extraction failed: $VIDEO_PATH" >&2
    fi
  fi

  return 1
}

if [[ ! -f "$VIDEO_PATH" ]]; then
  echo "video file not found: $VIDEO_PATH" >&2
  exit 1
fi

require_command ffmpeg

mkdir -p "$OUTPUT_DIR"
clear_existing_frames

FILTER=""
EXTRA_ARGS=()

case "$FRAME_MODE" in
  interval)
    require_positive_number "$FRAME_INTERVAL_SECONDS" "FRAME_INTERVAL_SECONDS"
    FILTER="fps=1/${FRAME_INTERVAL_SECONDS},scale=960:-1"
    ;;
  count)
    require_command ffprobe
    require_positive_integer "$FRAME_COUNT" "FRAME_COUNT"

    DURATION="$(ffprobe -v error -show_entries format=duration -of csv=p=0 "$VIDEO_PATH")"
    if [[ -z "$DURATION" || "$DURATION" == "N/A" ]]; then
      echo "could not determine video duration for count-based extraction: $VIDEO_PATH" >&2
      exit 1
    fi

    FRAME_INTERVAL_SECONDS="$(calc_even_interval "$DURATION" "$FRAME_COUNT")"
    FILTER="fps=1/${FRAME_INTERVAL_SECONDS},scale=960:-1"
    ;;
  scenes)
    FILTER="select='gt(scene,0.4)',scale=960:-1"
    EXTRA_ARGS=(-vsync vfr)
    ;;
  *)
    echo "FRAME_MODE must be one of: interval, count, scenes" >&2
    exit 1
    ;;
esac

CMD=(
  ffmpeg -y
  -i "$VIDEO_PATH"
  -vf "$FILTER"
)

if [[ ${#EXTRA_ARGS[@]} -gt 0 ]]; then
  CMD+=("${EXTRA_ARGS[@]}")
fi

CMD+=("${OUTPUT_DIR}/frame-%03d.jpg")

if [[ "$FRAME_MODE" == "scenes" ]]; then
  if ! run_ffmpeg 1 || ! has_output_frames; then
    clear_existing_frames
    require_positive_integer "$FRAME_COUNT" "FRAME_COUNT"
    DURATION="$(ffprobe -v error -show_entries format=duration -of csv=p=0 "$VIDEO_PATH")"
    if [[ -z "$DURATION" || "$DURATION" == "N/A" ]]; then
      echo "could not determine video duration for scene fallback extraction: $VIDEO_PATH" >&2
      exit 1
    fi

    FRAME_INTERVAL_SECONDS="$(calc_even_interval "$DURATION" "$FRAME_COUNT")"
    CMD=(
      ffmpeg -y
      -i "$VIDEO_PATH"
      -vf "fps=1/${FRAME_INTERVAL_SECONDS},scale=960:-1"
      "${OUTPUT_DIR}/frame-%03d.jpg"
    )
    run_ffmpeg
  fi
else
  run_ffmpeg
fi

echo "$OUTPUT_DIR"
