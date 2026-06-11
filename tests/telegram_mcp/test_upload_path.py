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


def test_resolve_upload_path_denies_nested_sensitive_paths(monkeypatch, tmp_path):
    fake_home = tmp_path / "home"
    nested = fake_home / ".ssh" / "keys"
    nested.mkdir(parents=True)
    secret = nested / "id_ed25519"
    secret.write_text("private", encoding="utf-8")
    monkeypatch.setattr(Path, "home", classmethod(lambda _cls: fake_home))
    monkeypatch.setenv("CODEX_TELEGRAM_UPLOAD_DIR", str(tmp_path / "uploads"))

    with pytest.raises(PermissionError, match="sensitive"):
        resolve_upload_path(str(secret), allow_arbitrary_path=True)


def test_resolve_upload_path_allows_sibling_of_denied_prefix(monkeypatch, tmp_path):
    # `.ssh-backup` shares a string prefix with `.ssh` but is a different
    # directory; component-wise matching must not over-block it.
    fake_home = tmp_path / "home"
    sibling = fake_home / ".ssh-backup"
    sibling.mkdir(parents=True)
    file_path = sibling / "notes.txt"
    file_path.write_text("ok", encoding="utf-8")
    monkeypatch.setattr(Path, "home", classmethod(lambda _cls: fake_home))
    monkeypatch.setenv("CODEX_TELEGRAM_UPLOAD_DIR", str(tmp_path / "uploads"))

    resolved, warning = resolve_upload_path(str(file_path), allow_arbitrary_path=True)

    assert resolved == file_path.resolve()
    assert warning is not None
