---
name: telegram-media-inspect
description: This skill should be used when the user asks to "watch this Telegram bubble", "listen to this Telegram voice note", "transcribe this Telegram audio", "see what this Telegram video says", "inspect this Telegram media", "check this Telegram video note", or wants help understanding audio/video content from the Telegram plugin.
---

Inspect and transcribe Telegram media with the plugin's existing media tools plus the bundled helper scripts in this skill.

Use this skill when the user cares about the contents of a voice note, video note, audio file, or video attachment, not just its metadata.

Workflow:

1. Resolve the target message first.
   - If the user gives a `chat_ref` and `message_id`, use them directly.
   - If the user only gives a chat and rough description like "that bubble", use `get_dialog`, `get_history`, or `search_messages_in_chat` to identify the right message before downloading anything.

2. Inspect the media type before choosing the workflow.
   - Call `get_media_info` to confirm whether the message is audio, video, voice note, or another attachment.
   - Treat circular "Telegram bubbles" as either voice notes or video notes depending on the returned media metadata.

3. Download the media locally.
   - Call `download_media` for the specific `message_id`.
   - Prefer a dedicated working directory so follow-up steps can reuse the files.

4. Transcribe audio-bearing media with the bundled script.
   - Run `scripts/transcribe_media.sh <downloaded_file> [output_dir]`.
   - The script bootstraps an isolated Whisper environment under `~/.cache/codex-telegram-plugin/whisper-venv` on first use.
   - Override the model with `WHISPER_MODEL=tiny|base|small|medium|large`. Default is `tiny` for a faster first pass.
   - Optionally set `WHISPER_LANGUAGE=English` or another language when the clip language is known.

5. Inspect video bubbles visually when needed.
   - Run `scripts/extract_video_frames.sh <downloaded_file> [output_dir]` to create representative still frames.
   - Review the extracted frames with the local image-viewing surface when the user asks what the clip shows visually or when transcript context alone is not enough.

6. Report results in two layers.
   - First give the literal content: transcript or best-effort quoted lines.
   - Then give the interpretation: what happened, what the speaker meant, and any actionables or social context.

7. Be explicit about uncertainty.
   - If the transcript is partial, noisy, or cut off, say so.
   - Distinguish between exact transcription and inference from surrounding chat context.

8. Do not send, forward, or delete the media unless the user explicitly asks.

Bundled scripts:

- `scripts/transcribe_media.sh`
  - Bootstraps Whisper in an isolated cache venv and writes transcript files next to the media or into the provided output directory.
- `scripts/extract_video_frames.sh`
  - Extracts evenly spaced JPG frames from a Telegram video/video-note for visual inspection.

Practical defaults:

- Start with transcription for voice notes, audio files, and most talking-head videos.
- Add frame extraction when the user says "watch", "see", "what's happening in the bubble", or when the visual context matters.
- For short social clips, a concise summary plus 1-3 notable quoted lines is usually more useful than dumping the whole transcript.
