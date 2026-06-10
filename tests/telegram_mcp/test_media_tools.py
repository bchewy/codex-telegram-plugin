from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest

from codex_telegram.tools import media


class _FakeMCP:
    def __init__(self):
        self.tools: dict[str, object] = {}

    def tool(self):
        def decorator(fn):
            self.tools[fn.__name__] = fn
            return fn

        return decorator


def _async_value(value):
    async def inner(*_args, **_kwargs):
        return value

    return inner


def _tool_from(name: str):
    mcp = _FakeMCP()
    media.register(mcp)
    return mcp.tools[name]


class _FakeProcess:
    def __init__(self, *, stdout: bytes, stderr: bytes = b"", returncode: int = 0):
        self._stdout = stdout
        self._stderr = stderr
        self.returncode = returncode

    async def communicate(self):
        return self._stdout, self._stderr


def test_resolve_skill_script_uses_env_override(monkeypatch, tmp_path):
    script_dir = tmp_path / "scripts"
    script_dir.mkdir()
    script = script_dir / "inspect_bubble.sh"
    script.write_text("#!/usr/bin/env bash\n", encoding="utf-8")

    monkeypatch.setenv("CODEX_TELEGRAM_MEDIA_SCRIPTS_DIR", str(script_dir))

    assert media._resolve_skill_script("inspect_bubble.sh") == script.resolve()


def test_resolve_skill_script_rejects_directory_override(monkeypatch, tmp_path):
    script_dir = tmp_path / "scripts"
    script_dir.mkdir()
    (script_dir / "inspect_bubble.sh").mkdir()

    monkeypatch.setenv("CODEX_TELEGRAM_MEDIA_SCRIPTS_DIR", str(script_dir))

    with pytest.raises(FileNotFoundError):
        media._resolve_skill_script("inspect_bubble.sh")


def test_resolve_skill_script_walks_up_to_plugin_root(monkeypatch, tmp_path):
    plugin_root = tmp_path / "telegram"
    script = plugin_root / "skills" / "telegram-media-inspect" / "scripts" / "inspect_bubble.sh"
    script.parent.mkdir(parents=True)
    script.write_text("#!/usr/bin/env bash\n", encoding="utf-8")

    fake_media_py = plugin_root / "mcp_server" / "src" / "codex_telegram" / "tools" / "media.py"
    fake_media_py.parent.mkdir(parents=True)
    fake_media_py.write_text("# test\n", encoding="utf-8")

    monkeypatch.delenv("CODEX_TELEGRAM_MEDIA_SCRIPTS_DIR", raising=False)
    monkeypatch.setattr(media, "__file__", str(fake_media_py))

    assert media._resolve_skill_script("inspect_bubble.sh") == script


def test_inspect_message_media_downloads_and_runs_script(monkeypatch):
    tool = _tool_from("inspect_message_media")

    client = SimpleNamespace(download_media=_async_value("/tmp/video.mp4"))
    entity = SimpleNamespace(id=1)
    message = SimpleNamespace(id=42)
    captured: dict[str, object] = {}

    async def fake_create_subprocess_exec(*args, **kwargs):
        captured["args"] = args
        captured["kwargs"] = kwargs
        return _FakeProcess(
            stdout=(
                b'{"transcript_path":"/tmp/video.txt",'
                b'"contact_sheet_path":"/tmp/contact.jpg",'
                b'"frames_dir":"/tmp/frames"}\n'
            )
        )

    monkeypatch.setattr(media, "get_client", _async_value(client))
    monkeypatch.setattr(media, "_resolve_message", _async_value((entity, message)))
    monkeypatch.setattr(media, "ensure_download_dir", lambda _value: Path("/tmp/out"))
    monkeypatch.setattr(media, "_resolve_skill_script", lambda _name: Path("/fake/inspect_bubble.sh"))
    monkeypatch.setattr(media, "peer_ref", lambda _entity: "chat:1")
    monkeypatch.setattr(media.asyncio, "create_subprocess_exec", fake_create_subprocess_exec)

    result = asyncio.run(tool(chat_ref="chat:1", message_id=42, output_dir="/tmp/out"))

    assert captured["args"] == ("bash", "/fake/inspect_bubble.sh", "/tmp/video.mp4", "/tmp/out")
    assert result == {
        "transcript_path": "/tmp/video.txt",
        "contact_sheet_path": "/tmp/contact.jpg",
        "frames_dir": "/tmp/frames",
        "chat_ref": "chat:1",
        "message_id": 42,
        "downloaded_to": "/tmp/video.mp4",
    }


def test_inspect_message_media_uses_script_default_output_dir_when_unspecified(monkeypatch):
    tool = _tool_from("inspect_message_media")

    client = SimpleNamespace(download_media=_async_value("/tmp/video.mp4"))
    entity = SimpleNamespace(id=1)
    message = SimpleNamespace(id=42)
    captured: dict[str, object] = {}

    async def fake_create_subprocess_exec(*args, **kwargs):
        captured["args"] = args
        captured["kwargs"] = kwargs
        return _FakeProcess(stdout=b'{"transcript_path":"/tmp/video.txt"}\n')

    monkeypatch.setattr(media, "get_client", _async_value(client))
    monkeypatch.setattr(media, "_resolve_message", _async_value((entity, message)))
    monkeypatch.setattr(media, "ensure_download_dir", lambda _value: Path("/tmp/downloads"))
    monkeypatch.setattr(media, "_resolve_skill_script", lambda _name: Path("/fake/inspect_bubble.sh"))
    monkeypatch.setattr(media, "peer_ref", lambda _entity: "chat:1")
    monkeypatch.setattr(media.asyncio, "create_subprocess_exec", fake_create_subprocess_exec)

    result = asyncio.run(tool(chat_ref="chat:1", message_id=42))

    assert captured["args"] == ("bash", "/fake/inspect_bubble.sh", "/tmp/video.mp4")
    assert result["downloaded_to"] == "/tmp/video.mp4"


def test_inspect_media_file_raises_for_nonzero_exit(monkeypatch):
    async def fake_create_subprocess_exec(*_args, **_kwargs):
        return _FakeProcess(returncode=1, stderr=b"boom\n", stdout=b"")

    monkeypatch.setattr(media.asyncio, "create_subprocess_exec", fake_create_subprocess_exec)

    with pytest.raises(RuntimeError, match="boom"):
        asyncio.run(media._inspect_media_file(Path("/fake/inspect_bubble.sh"), "/tmp/video.mp4"))


def test_inspect_media_file_rejects_non_object_json(monkeypatch):
    async def fake_create_subprocess_exec(*_args, **_kwargs):
        return _FakeProcess(returncode=0, stderr=b"", stdout=b'["not", "an", "object"]\n')

    monkeypatch.setattr(media.asyncio, "create_subprocess_exec", fake_create_subprocess_exec)

    with pytest.raises(RuntimeError, match="expected object"):
        asyncio.run(media._inspect_media_file(Path("/fake/inspect_bubble.sh"), "/tmp/video.mp4"))
