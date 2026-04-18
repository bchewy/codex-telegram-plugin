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
