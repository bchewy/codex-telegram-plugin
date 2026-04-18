from __future__ import annotations

from pathlib import Path

import pytest

from codex_telegram.helpers import resolve_upload_path


def test_resolve_upload_path_allows_files_in_sandbox(monkeypatch, tmp_path):
    sandbox = tmp_path / "uploads"
    sandbox.mkdir()
    file_path = sandbox / "photo.jpg"
    file_path.write_text("ok", encoding="utf-8")
    monkeypatch.setenv("CODEX_TELEGRAM_UPLOAD_DIR", str(sandbox))

    resolved, warning = resolve_upload_path(str(file_path), allow_arbitrary_path=False)

    assert resolved == file_path.resolve()
    assert warning is None


def test_resolve_upload_path_rejects_files_outside_sandbox(monkeypatch, tmp_path):
    sandbox = tmp_path / "uploads"
    sandbox.mkdir()
    file_path = tmp_path / "photo.jpg"
    file_path.write_text("ok", encoding="utf-8")
    monkeypatch.setenv("CODEX_TELEGRAM_UPLOAD_DIR", str(sandbox))

    with pytest.raises(PermissionError, match="outside"):
        resolve_upload_path(str(file_path), allow_arbitrary_path=False)


def test_resolve_upload_path_allows_escape_hatch_with_warning(monkeypatch, tmp_path):
    sandbox = tmp_path / "uploads"
    sandbox.mkdir()
    file_path = tmp_path / "photo.jpg"
    file_path.write_text("ok", encoding="utf-8")
    monkeypatch.setenv("CODEX_TELEGRAM_UPLOAD_DIR", str(sandbox))

    resolved, warning = resolve_upload_path(str(file_path), allow_arbitrary_path=True)

    assert resolved == file_path.resolve()
    assert "outside sandbox" in warning


def test_resolve_upload_path_rejects_sensitive_paths(monkeypatch, tmp_path):
    home = tmp_path / "home"
    sensitive = home / ".ssh" / "id_rsa"
    sensitive.parent.mkdir(parents=True)
    sensitive.write_text("secret", encoding="utf-8")
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("CODEX_TELEGRAM_UPLOAD_DIR", str(home / "uploads"))

    with pytest.raises(PermissionError, match="sensitive path"):
        resolve_upload_path(str(sensitive), allow_arbitrary_path=True)
