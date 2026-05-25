#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 1 || $# -gt 2 ]]; then
  echo "usage: $0 <frames_dir> [output_path]" >&2
  exit 1
fi

FRAMES_DIR="$1"
OUTPUT_PATH="${2:-${FRAMES_DIR}/contact-sheet.jpg}"
COLUMNS="${SHEET_COLUMNS:-4}"
ROWS="${SHEET_ROWS:-}"

require_positive_integer() {
  local value="$1"
  local label="$2"

  if [[ ! "$value" =~ ^[1-9][0-9]*$ ]]; then
    echo "${label} must be a positive integer: ${value}" >&2
    exit 1
  fi
}

if [[ ! -d "$FRAMES_DIR" ]]; then
  echo "frames directory not found: $FRAMES_DIR" >&2
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

require_positive_integer "$COLUMNS" "SHEET_COLUMNS"

shopt -s nullglob
FRAME_FILES=("$FRAMES_DIR"/frame-*.jpg)
shopt -u nullglob

if [[ ${#FRAME_FILES[@]} -eq 0 ]]; then
  echo "no frame-*.jpg files found in: $FRAMES_DIR" >&2
  exit 1
fi

SORTED_FRAME_FILES=()
while IFS= read -r frame_file; do
  SORTED_FRAME_FILES+=("$frame_file")
done < <(
  python3 - <<'PY' "${FRAME_FILES[@]}"
import re
import sys


def frame_key(path):
    match = re.search(r"frame-(\d+)\.jpg$", path)
    if match is None:
        return -1
    return int(match.group(1))


for item in sorted(sys.argv[1:], key=frame_key):
    print(item)
PY
)

FRAME_FILES=("${SORTED_FRAME_FILES[@]}")

if [[ -n "$ROWS" ]]; then
  require_positive_integer "$ROWS" "SHEET_ROWS"
  if (( COLUMNS * ROWS < ${#FRAME_FILES[@]} )); then
    echo "SHEET_COLUMNS=${COLUMNS} and SHEET_ROWS=${ROWS} can only hold $(( COLUMNS * ROWS )) frames, but ${#FRAME_FILES[@]} were provided." >&2
    exit 1
  fi
else
  ROWS="$(( (${#FRAME_FILES[@]} + COLUMNS - 1) / COLUMNS ))"
fi

mkdir -p "$(dirname "$OUTPUT_PATH")"

SEQUENCE_DIR="$(mktemp -d)"
cleanup() {
  rm -rf "$SEQUENCE_DIR"
}
trap cleanup EXIT

FRAME_INDEX=1
for frame_file in "${FRAME_FILES[@]}"; do
  cp "$frame_file" "$(printf "%s/frame-%03d.jpg" "$SEQUENCE_DIR" "$FRAME_INDEX")"
  FRAME_INDEX=$((FRAME_INDEX + 1))
done

STDERR_FILE="$(mktemp)"
if ! ffmpeg -y \
  -start_number 1 \
  -i "${SEQUENCE_DIR}/frame-%03d.jpg" \
  -vf "tile=${COLUMNS}x${ROWS}:padding=4:margin=4" \
  -frames:v 1 \
  "$OUTPUT_PATH" \
  >/dev/null 2>"$STDERR_FILE"; then
  ERROR_OUTPUT="$(<"$STDERR_FILE")"
  rm -f "$STDERR_FILE"
  if [[ -n "$ERROR_OUTPUT" ]]; then
    echo "$ERROR_OUTPUT" >&2
  else
    echo "ffmpeg contact-sheet generation failed: $FRAMES_DIR" >&2
  fi
  exit 1
fi
rm -f "$STDERR_FILE"

echo "$OUTPUT_PATH"
