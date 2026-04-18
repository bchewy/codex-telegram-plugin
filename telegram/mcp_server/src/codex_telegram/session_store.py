from __future__ import annotations

import base64
import getpass
import json
from json import JSONDecodeError
import os
from pathlib import Path
from typing import Any

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
import keyring
from keyring.errors import KeyringError, NoKeyringError

from .models import StoredSession

SERVICE_NAME = "codex-telegram-plugin"
ACCOUNT_NAME = "default"
SESSION_ENV_VAR = "CODEX_TELEGRAM_SESSION"
MASTER_KEY_ENV_VAR = "CODEX_TELEGRAM_MASTER_KEY"
CONFIG_DIR_ENV_VAR = "CODEX_TELEGRAM_CONFIG_DIR"
SESSION_FILE_NAME = "session.enc"
PBKDF2_ITERATIONS = 390_000


class SessionStoreError(RuntimeError):
    pass


class MissingSessionError(SessionStoreError):
    pass


def _config_dir() -> Path:
    override = os.getenv(CONFIG_DIR_ENV_VAR)
    if override:
        return Path(override).expanduser().resolve()
    return Path.home() / ".config" / "codex-telegram"


def _session_file() -> Path:
    return _config_dir() / SESSION_FILE_NAME


def _derive_fernet(master_key: str, salt: bytes) -> Fernet:
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=PBKDF2_ITERATIONS,
    )
    key = base64.urlsafe_b64encode(kdf.derive(master_key.encode("utf-8")))
    return Fernet(key)


def _encrypt_payload(payload: str, master_key: str) -> dict[str, str]:
    salt = os.urandom(16)
    token = _derive_fernet(master_key, salt).encrypt(payload.encode("utf-8"))
    return {
        "salt": base64.urlsafe_b64encode(salt).decode("ascii"),
        "token": token.decode("ascii"),
    }


def _decrypt_payload(payload: dict[str, str], master_key: str) -> str:
    salt = base64.urlsafe_b64decode(payload["salt"].encode("ascii"))
    try:
        return _derive_fernet(master_key, salt).decrypt(
            payload["token"].encode("ascii")
        ).decode("utf-8")
    except InvalidToken as exc:
        raise SessionStoreError(
            "Encrypted Telegram session could not be decrypted. "
            "Check CODEX_TELEGRAM_MASTER_KEY."
        ) from exc


def _ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def _write_encrypted_file(record: StoredSession, master_key: str) -> None:
    file_path = _session_file()
    _ensure_parent(file_path)
    payload = _encrypt_payload(record.to_json(), master_key)
    file_path.write_text(json.dumps(payload), encoding="utf-8")
    os.chmod(file_path, 0o600)


def _prompt_master_key(prompt: str = "Telegram session master key: ") -> str:
    value = getpass.getpass(prompt).strip()
    if not value:
        raise SessionStoreError("A Telegram session master key is required to continue.")
    return value


def _read_encrypted_file(master_key: str | None) -> StoredSession | None:
    file_path = _session_file()
    if not file_path.exists():
        return None
    master_key = master_key or os.getenv(MASTER_KEY_ENV_VAR)
    if not master_key:
        raise MissingSessionError(
            "Encrypted Telegram session found, but no master key was provided. "
            "Set CODEX_TELEGRAM_MASTER_KEY and retry."
        )
    payload = json.loads(file_path.read_text(encoding="utf-8"))
    return StoredSession.from_json(_decrypt_payload(payload, master_key))


def _read_keyring() -> StoredSession | None:
    try:
        raw = keyring.get_password(SERVICE_NAME, ACCOUNT_NAME)
    except (KeyringError, NoKeyringError):
        return None
    if not raw:
        return None
    try:
        return StoredSession.from_json(raw)
    except JSONDecodeError:
        return None


def _write_keyring(record: StoredSession) -> bool:
    try:
        keyring.set_password(SERVICE_NAME, ACCOUNT_NAME, record.to_json())
        return True
    except (KeyringError, NoKeyringError):
        return False


def load_session(master_key: str | None = None) -> StoredSession:
    raw_env_session = os.getenv(SESSION_ENV_VAR)
    api_id = os.getenv("TG_API_ID")
    api_hash = os.getenv("TG_API_HASH")
    if raw_env_session and api_id and api_hash:
        return StoredSession(
            api_id=int(api_id),
            api_hash=api_hash,
            session_string=raw_env_session,
        )

    keyring_session = _read_keyring()
    if keyring_session:
        return keyring_session

    encrypted_session = _read_encrypted_file(master_key)
    if encrypted_session:
        return encrypted_session

    raise MissingSessionError(
        "No Telegram session found. Run `python -m codex_telegram login` first."
    )


def save_session(
    record: StoredSession,
    master_key: str | None = None,
    *,
    prompt_if_missing: bool = False,
) -> str:
    if _write_keyring(record):
        return "keyring"

    master_key = master_key or os.getenv(MASTER_KEY_ENV_VAR)
    if not master_key:
        if prompt_if_missing:
            master_key = _prompt_master_key()
        else:
            raise SessionStoreError(
                "The OS keyring is unavailable. Set CODEX_TELEGRAM_MASTER_KEY "
                "so the plugin can use the encrypted file fallback."
            )

    _write_encrypted_file(record, master_key)
    return "encrypted-file"


def clear_session(master_key: str | None = None, *, prompt_if_missing: bool = False) -> bool:
    removed = False

    try:
        keyring.delete_password(SERVICE_NAME, ACCOUNT_NAME)
        removed = True
    except (KeyringError, NoKeyringError):
        pass

    file_path = _session_file()
    if file_path.exists():
        master_key = master_key or os.getenv(MASTER_KEY_ENV_VAR)
        if not master_key:
            if prompt_if_missing:
                master_key = _prompt_master_key()
            else:
                raise MissingSessionError(
                    "Encrypted Telegram session exists. Provide CODEX_TELEGRAM_MASTER_KEY "
                    "to clear it."
                )
        file_path.unlink()
        removed = True

    return removed


def describe_storage() -> dict[str, Any]:
    keyring_session = _read_keyring()
    file_exists = _session_file().exists()
    return {
        "service_name": SERVICE_NAME,
        "keyring_session_present": keyring_session is not None,
        "encrypted_file_exists": file_exists,
        "session_file": str(_session_file()),
    }
