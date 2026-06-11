from __future__ import annotations

from codex_telegram.models import StoredSession
from codex_telegram import session_store


def _sample_session() -> StoredSession:
    return StoredSession(
        api_id=12345,
        api_hash="hash",
        session_string="session-string",
        phone="+15555555555",
        user_id=42,
        username="alice",
        display_name="Alice",
    )


def test_keyring_roundtrip(monkeypatch, tmp_path):
    monkeypatch.setenv(session_store.CONFIG_DIR_ENV_VAR, str(tmp_path))
    store: dict[tuple[str, str], str] = {}

    monkeypatch.setattr(
        session_store.keyring,
        "set_password",
        lambda service, account, value: store.__setitem__((service, account), value),
    )
    monkeypatch.setattr(
        session_store.keyring,
        "get_password",
        lambda service, account: store.get((service, account)),
    )
    monkeypatch.setattr(
        session_store.keyring,
        "delete_password",
        lambda service, account: store.pop((service, account), None),
    )

    session = _sample_session()
    backend = session_store.save_session(session)
    loaded = session_store.load_session()

    assert backend == "keyring"
    assert loaded == session
    assert session_store.clear_session() is True


def test_encrypted_file_fallback(monkeypatch, tmp_path):
    monkeypatch.setenv(session_store.CONFIG_DIR_ENV_VAR, str(tmp_path))
    monkeypatch.setenv(session_store.MASTER_KEY_ENV_VAR, "super-secret-master-key")

    def _raise(*_args, **_kwargs):
        raise session_store.NoKeyringError()

    monkeypatch.setattr(session_store.keyring, "set_password", _raise)
    monkeypatch.setattr(session_store.keyring, "get_password", _raise)
    monkeypatch.setattr(session_store.keyring, "delete_password", _raise)

    session = _sample_session()
    backend = session_store.save_session(session)
    loaded = session_store.load_session()

    assert backend == "encrypted-file"
    assert loaded == session
    assert session_store._session_file().exists()
    assert session_store.clear_session() is True


def test_keyring_payload_with_unknown_keys_still_loads(monkeypatch, tmp_path):
    monkeypatch.setenv(session_store.CONFIG_DIR_ENV_VAR, str(tmp_path))
    monkeypatch.delenv(session_store.SESSION_ENV_VAR, raising=False)
    payload = _sample_session().to_json()
    # Simulate a payload written by a newer plugin version with extra fields.
    import json

    data = json.loads(payload)
    data["future_field"] = "surprise"
    monkeypatch.setattr(
        session_store.keyring,
        "get_password",
        lambda service, account: json.dumps(data),
    )

    loaded = session_store.load_session()

    assert loaded.api_id == 12345
    assert loaded.username == "alice"


def test_malformed_keyring_payload_falls_through(monkeypatch, tmp_path):
    monkeypatch.setenv(session_store.CONFIG_DIR_ENV_VAR, str(tmp_path))
    monkeypatch.delenv(session_store.SESSION_ENV_VAR, raising=False)
    # JSON that decodes but cannot construct a StoredSession (missing
    # required fields) must fall through, not crash load_session.
    monkeypatch.setattr(
        session_store.keyring,
        "get_password",
        lambda service, account: '{"unexpected": true}',
    )

    import pytest

    with pytest.raises(session_store.MissingSessionError):
        session_store.load_session()


def test_clear_session_removes_encrypted_file_without_master_key(monkeypatch, tmp_path):
    monkeypatch.setenv(session_store.CONFIG_DIR_ENV_VAR, str(tmp_path))
    monkeypatch.delenv(session_store.MASTER_KEY_ENV_VAR, raising=False)
    monkeypatch.setattr(
        session_store.keyring,
        "delete_password",
        lambda service, account: (_ for _ in ()).throw(session_store.NoKeyringError()),
    )
    session_file = tmp_path / session_store.SESSION_FILE_NAME
    session_file.write_text("{}", encoding="utf-8")

    # Deleting a file never needed the decryption key; logout must work
    # non-interactively.
    assert session_store.clear_session() is True
    assert not session_file.exists()


def test_encrypted_file_written_atomically_with_owner_only_permissions(monkeypatch, tmp_path):
    monkeypatch.setenv(session_store.CONFIG_DIR_ENV_VAR, str(tmp_path))
    monkeypatch.setattr(
        session_store.keyring,
        "set_password",
        lambda service, account, value: (_ for _ in ()).throw(session_store.NoKeyringError()),
    )

    backend = session_store.save_session(_sample_session(), master_key="hunter2")

    session_file = tmp_path / session_store.SESSION_FILE_NAME
    assert backend == "encrypted-file"
    assert session_file.exists()
    assert (session_file.stat().st_mode & 0o777) == 0o600
    # No temp file left behind.
    assert list(tmp_path.glob("*.tmp")) == []
