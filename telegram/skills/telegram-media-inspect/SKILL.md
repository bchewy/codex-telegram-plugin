---
name: telegram-media-inspect
description: Use when the user asks to inspect, watch, listen to, transcribe, or understand Telegram voice notes, video notes, audio files, videos, or other message media.
---

Inspect Telegram media with the plugin's media tools plus the bundled one-shot inspection scripts in this skill.

Use this skill when the user cares about the contents of a voice note, video note, audio file, or video attachment, not just its metadata.

Primary workflow:

1. Resolve the target message first.
   - If the user gives a `chat_ref` and `message_id`, use them directly.
   - If the user only gives a chat and rough description like "that bubble", use `get_dialog`, `get_history`, `get_message_context`, or `search_messages_in_chat` to identify the right message before downloading anything.

2. Confirm the media type when needed.
   - Call `get_media_info` if you need to distinguish audio, voice note, video note, or another attachment before downloading.
   - Treat circular "Telegram bubbles" as either voice notes or video notes depending on the returned media metadata.

3. Prefer the thin MCP wrapper when available.
   - Call `inspect_message_media(chat_ref, message_id, output_dir?)`.
   - It downloads the media, runs the one-shot inspector, and returns:
     - `transcript_path`
     - `contact_sheet_path`
     - `frames_dir`
     - `downloaded_to`
   - When `output_dir` is provided, results are still written into a per-media `<media-basename>-inspect/` subdirectory so repeated inspections do not clobber each other.

4. Fall back to the script path when needed.
   - If you need to debug locally or the wrapper is unavailable, call `download_media` for the specific `message_id`, then run `scripts/inspect_bubble.sh <downloaded_file> [output_dir]`.
   - `inspect_bubble.sh` prints one JSON object on stdout with the same path fields.
   - If you pass `output_dir`, the script writes into `<output_dir>/<media-basename>-inspect/`.
   - `transcript_path` is populated when the file has audio.
   - `contact_sheet_path` is populated when the file has video.

5. Read the outputs locally.
   - Read the transcript file when `transcript_path` is present.
   - Read the contact-sheet image when `contact_sheet_path` is present.
   - Use both when the user asks to "watch" a video bubble, since the speech and visuals often both matter.

6. Report results in two layers.
   - First give the literal content: transcript or best-effort quoted lines.
   - Then give the interpretation: what happened, what the speaker meant, what was shown visually, and any actionables or social context.

7. Be explicit about uncertainty.
   - If the transcript is partial, noisy, or cut off, say so.
   - If the contact sheet misses context between sampled frames, say so.
   - Distinguish between exact transcription and inference from the visual samples or surrounding chat context.

8. Do not send, forward, or delete the media unless the user explicitly asks.

What `inspect_bubble.sh` does:

- If the media has audio, it runs `scripts/transcribe_media.sh`.
- If the media has video, it runs `scripts/extract_video_frames.sh` and `scripts/make_contact_sheet.sh`.
- It defaults video sampling to evenly spaced frame-count mode so long clips do not explode into hundreds of JPGs.
- `inspect_message_media` is the MCP wrapper around this same shell workflow.

Advanced overrides:

- `WHISPER_MODEL=tiny|base|small|medium|large`
- `WHISPER_LANGUAGE=English` or another known language
- `FRAME_MODE=interval|count|scenes`
- `FRAME_COUNT=8` for evenly spaced frame sampling
- `FRAME_INTERVAL_SECONDS=8` for interval mode
- `SHEET_COLUMNS=4`
- `SHEET_ROWS=<n>` if you want to force a fixed grid; otherwise rows expand to fit all extracted frames. If you set it manually, it must be large enough for every extracted frame.

Bundled scripts:

- `scripts/inspect_bubble.sh`
  - One-shot wrapper that returns transcript and/or contact-sheet paths as JSON.
- `scripts/transcribe_media.sh`
  - Bootstraps Whisper in an isolated cache venv and writes a `.txt` transcript next to the media or into the provided output directory.
- `scripts/extract_video_frames.sh`
  - Extracts JPG frames from a Telegram video/video-note using interval, even-count, or scene-change sampling.
- `scripts/make_contact_sheet.sh`
  - Turns the extracted `frame-*.jpg` files into one tiled JPG for quick visual inspection.

Practical defaults:

- Start with `inspect_message_media` when the MCP wrapper is available.
- Use `inspect_bubble.sh` when debugging locally or when you want to bypass the MCP layer.
- For voice notes and audio files, the transcript is usually the whole answer.
- For video bubbles, read both the transcript and the contact sheet before summarizing.
- For short social clips, a concise summary plus 1-3 notable quoted lines is usually more useful than dumping the whole transcript.
