from __future__ import annotations

from datetime import UTC, datetime
import importlib
import json
import os
from pathlib import Path
import sqlite3
from typing import Any

from .helpers import parse_datetime, to_iso
from .session_store import MASTER_KEY_ENV_VAR

CACHE_ENCRYPT_ENV_VAR = "CODEX_TELEGRAM_CACHE_ENCRYPT"
CACHE_FILE_NAME = "cache.db"
SCHEMA_VERSION = 2

_MIGRATIONS = {
    1: """
    CREATE TABLE IF NOT EXISTS messages (
      chat_ref TEXT NOT NULL,
      id INTEGER NOT NULL,
      date INTEGER NOT NULL,
      sender_ref TEXT,
      sender_name TEXT,
      text TEXT,
      reply_to_id INTEGER,
      raw_json TEXT NOT NULL,
      PRIMARY KEY (chat_ref, id)
    );
    CREATE INDEX IF NOT EXISTS idx_msg_date ON messages(chat_ref, date);
    CREATE INDEX IF NOT EXISTS idx_msg_sender ON messages(chat_ref, sender_ref, date);

    CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts USING fts5(
      text,
      content='messages',
      content_rowid='rowid',
      tokenize='unicode61 remove_diacritics 2'
    );

    CREATE TABLE IF NOT EXISTS chat_sync_state (
      chat_ref TEXT PRIMARY KEY,
      max_cached_id INTEGER NOT NULL,
      last_synced_at INTEGER NOT NULL
    );

    CREATE TRIGGER IF NOT EXISTS messages_ai AFTER INSERT ON messages BEGIN
      INSERT INTO messages_fts(rowid, text) VALUES (new.rowid, new.text);
    END;

    CREATE TRIGGER IF NOT EXISTS messages_ad AFTER DELETE ON messages BEGIN
      INSERT INTO messages_fts(messages_fts, rowid, text)
      VALUES ('delete', old.rowid, old.text);
    END;

    CREATE TRIGGER IF NOT EXISTS messages_au AFTER UPDATE ON messages BEGIN
      INSERT INTO messages_fts(messages_fts, rowid, text)
      VALUES ('delete', old.rowid, old.text);
      INSERT INTO messages_fts(rowid, text) VALUES (new.rowid, new.text);
    END;
    """,
    2: """
    CREATE INDEX IF NOT EXISTS idx_msg_chat_date_id ON messages(chat_ref, date, id);
    CREATE INDEX IF NOT EXISTS idx_msg_reply ON messages(chat_ref, reply_to_id);
    """,
}


def cache_db_path() -> Path:
    xdg_cache_home = os.getenv("XDG_CACHE_HOME")
    base_dir = Path(xdg_cache_home).expanduser() if xdg_cache_home else Path.home() / ".cache"
    cache_dir = base_dir / "codex-telegram"
    cache_dir.mkdir(parents=True, exist_ok=True)
    # The cache holds private message content; keep it owner-only even when
    # encryption is not enabled. Best-effort: failure to tighten permissions
    # must not break cache access itself.
    try:
        os.chmod(cache_dir, 0o700)
    except OSError:
        pass
    return cache_dir / CACHE_FILE_NAME


def cache_encryption_enabled() -> bool:
    return os.getenv(CACHE_ENCRYPT_ENV_VAR) == "1"


def _cache_driver():
    if not cache_encryption_enabled():
        return sqlite3
    try:
        return importlib.import_module("pysqlcipher3.dbapi2")
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "Encrypted Telegram cache requested, but pysqlcipher3 is not installed."
        ) from exc


def connect_cache(path: str | Path | None = None):
    driver = _cache_driver()
    target = path if path is not None else cache_db_path()
    target_str = str(target)
    if target_str != ":memory:":
        expanded = Path(target_str).expanduser().resolve()
        expanded.parent.mkdir(parents=True, exist_ok=True)

    connection = driver.connect(target_str)
    if target_str != ":memory:":
        try:
            os.chmod(expanded, 0o600)
        except OSError:
            pass
    try:
        # The pysqlcipher3 driver rejects stdlib sqlite3.Row, so always use
        # the connected driver's own Row type.
        connection.row_factory = driver.Row

        if cache_encryption_enabled():
            master_key = os.getenv(MASTER_KEY_ENV_VAR)
            if not master_key:
                raise RuntimeError(
                    "Encrypted Telegram cache requires CODEX_TELEGRAM_MASTER_KEY."
                )
            escaped_key = master_key.replace("'", "''")
            connection.execute(f"PRAGMA key = '{escaped_key}'")

        try:
            connection.execute("SELECT count(*) FROM sqlite_master")
        except driver.DatabaseError as exc:
            raise RuntimeError(
                f"Could not read the Telegram cache at {target_str}. This usually "
                f"means it was created with a different {CACHE_ENCRYPT_ENV_VAR} or "
                f"{MASTER_KEY_ENV_VAR} setting. Fix the environment or delete the "
                "cache file to rebuild it."
            ) from exc

        if target_str != ":memory:":
            connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA foreign_keys = ON")
    except BaseException:
        connection.close()
        raise
    return connection


def ensure_cache_schema(connection) -> None:
    connection.execute("CREATE TABLE IF NOT EXISTS schema_version (version INTEGER PRIMARY KEY)")
    row = connection.execute("SELECT MAX(version) AS version FROM schema_version").fetchone()
    current_version = int(row["version"] or 0)

    for version in range(current_version + 1, SCHEMA_VERSION + 1):
        connection.executescript(_MIGRATIONS[version])
        connection.execute("INSERT INTO schema_version(version) VALUES (?)", (version,))

    connection.commit()


def clear_chat_cache(connection, chat_ref: str) -> None:
    connection.execute("DELETE FROM messages WHERE chat_ref = ?", (chat_ref,))
    connection.execute("DELETE FROM chat_sync_state WHERE chat_ref = ?", (chat_ref,))


def _message_row(payload: dict[str, Any]) -> tuple[Any, ...]:
    parsed_date = parse_datetime(payload.get("date"))
    if parsed_date is None:
        raise ValueError(f"Cached message is missing a valid date: {payload.get('id')}")

    return (
        payload["chat_ref"],
        payload["id"],
        int(parsed_date.timestamp()),
        payload.get("sender_ref"),
        payload.get("sender_name"),
        payload.get("raw_text") or payload.get("text") or "",
        payload.get("reply_to_message_id"),
        json.dumps(payload, separators=(",", ":"), sort_keys=True),
    )


def upsert_cached_messages(connection, messages: list[dict[str, Any]]) -> int:
    rows = [_message_row(payload) for payload in messages]
    if not rows:
        return 0

    connection.executemany(
        """
        INSERT INTO messages (
          chat_ref,
          id,
          date,
          sender_ref,
          sender_name,
          text,
          reply_to_id,
          raw_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(chat_ref, id) DO UPDATE SET
          date = excluded.date,
          sender_ref = excluded.sender_ref,
          sender_name = excluded.sender_name,
          text = excluded.text,
          reply_to_id = excluded.reply_to_id,
          raw_json = excluded.raw_json
        """,
        rows,
    )
    return len(rows)


def get_chat_sync_state(connection, chat_ref: str) -> dict[str, Any] | None:
    row = connection.execute(
        "SELECT chat_ref, max_cached_id, last_synced_at FROM chat_sync_state WHERE chat_ref = ?",
        (chat_ref,),
    ).fetchone()
    if row is None:
        return None
    return {
        "chat_ref": row["chat_ref"],
        "max_cached_id": row["max_cached_id"],
        "last_synced_at": row["last_synced_at"],
    }


def update_chat_sync_state(connection, chat_ref: str, max_cached_id: int) -> None:
    connection.execute(
        """
        INSERT INTO chat_sync_state (chat_ref, max_cached_id, last_synced_at)
        VALUES (?, ?, ?)
        ON CONFLICT(chat_ref) DO UPDATE SET
          max_cached_id = excluded.max_cached_id,
          last_synced_at = excluded.last_synced_at
        """,
        (chat_ref, max_cached_id, int(datetime.now(tz=UTC).timestamp())),
    )


def _fts_match_query(query: str) -> str:
    terms = [term for term in query.split() if term]
    if not terms:
        return ""
    return " ".join('"' + term.replace('"', '""') + '"' for term in terms)


def _timestamp_bounds(min_date: str | None, max_date: str | None) -> tuple[int | None, int | None]:
    lower = parse_datetime(min_date)
    upper = parse_datetime(max_date)
    return (
        int(lower.timestamp()) if lower else None,
        int(upper.timestamp()) if upper else None,
    )


def search_cached_messages(
    connection,
    *,
    chat_ref: str | None = None,
    query: str | None = None,
    sender_ref: str | None = None,
    min_date: str | None = None,
    max_date: str | None = None,
    limit: int = 100,
    offset: int = 0,
    compact: bool = False,
    text_limit: int = 240,
    snippet_tokens: int = 12,
) -> list[dict[str, Any]]:
    if limit <= 0:
        return []
    if offset < 0:
        raise ValueError("offset must be >= 0")
    if text_limit <= 0:
        raise ValueError("text_limit must be > 0")

    lower, upper = _timestamp_bounds(min_date, max_date)
    select_params: list[Any] = []
    params: list[Any] = []
    where: list[str] = []
    fts_query = _fts_match_query(query or "")

    if fts_query:
        from_clause = "FROM messages JOIN messages_fts ON messages_fts.rowid = messages.rowid"
        where.append("messages_fts MATCH ?")
        params.append(fts_query)
        order_by = "ORDER BY rank, messages.date DESC, messages.id DESC"
    else:
        from_clause = "FROM messages"
        order_by = "ORDER BY messages.date DESC, messages.id DESC"

    if chat_ref:
        where.append("messages.chat_ref = ?")
        params.append(chat_ref)
    if sender_ref:
        where.append("messages.sender_ref = ?")
        params.append(sender_ref)
    if lower is not None:
        where.append("messages.date >= ?")
        params.append(lower)
    if upper is not None:
        where.append("messages.date <= ?")
        params.append(upper)

    if compact:
        if fts_query:
            select_clause = (
                "SELECT messages.chat_ref, messages.id, messages.date, messages.sender_ref, "
                "messages.sender_name, messages.text, messages.reply_to_id, "
                "snippet(messages_fts, 0, '[', ']', '…', ?) AS snippet, "
                "bm25(messages_fts) AS rank "
            )
            select_params.append(snippet_tokens)
        else:
            select_clause = (
                "SELECT messages.chat_ref, messages.id, messages.date, messages.sender_ref, "
                "messages.sender_name, messages.text, messages.reply_to_id, "
                "NULL AS snippet, NULL AS rank "
            )
    else:
        if fts_query:
            select_clause = "SELECT messages.raw_json, bm25(messages_fts) AS rank "
        else:
            select_clause = "SELECT messages.raw_json, NULL AS rank "

    sql = f"{select_clause}{from_clause}"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += f" {order_by} LIMIT ? OFFSET ?"
    params.extend([limit, offset])

    rows = connection.execute(sql, [*select_params, *params]).fetchall()
    if not compact:
        return [json.loads(row["raw_json"]) for row in rows]

    results = []
    for row in rows:
        text = row["text"] or ""
        preview = text if len(text) <= text_limit else text[: text_limit - 1].rstrip() + "…"
        results.append(
            {
                "chat_ref": row["chat_ref"],
                "id": row["id"],
                "date": to_iso(datetime.fromtimestamp(row["date"], tz=UTC)),
                "sender_ref": row["sender_ref"],
                "sender_name": row["sender_name"],
                "reply_to_message_id": row["reply_to_id"],
                "text": preview,
                "snippet": row["snippet"],
                "rank": row["rank"],
            }
        )
    return results


def _cached_message_where(
    *,
    chat_ref: str,
    min_date: str | None = None,
    max_date: str | None = None,
) -> tuple[str, list[Any]]:
    lower, upper = _timestamp_bounds(min_date, max_date)
    params: list[Any] = [chat_ref]
    where = ["chat_ref = ?"]
    if lower is not None:
        where.append("date >= ?")
        params.append(lower)
    if upper is not None:
        where.append("date <= ?")
        params.append(upper)
    return " AND ".join(where), params


def count_cached_messages(
    connection,
    *,
    chat_ref: str,
    min_date: str | None = None,
    max_date: str | None = None,
) -> int:
    where_sql, params = _cached_message_where(
        chat_ref=chat_ref,
        min_date=min_date,
        max_date=max_date,
    )
    row = connection.execute(
        f"SELECT COUNT(*) AS count FROM messages WHERE {where_sql}",
        params,
    ).fetchone()
    return int(row["count"] or 0)


def load_cached_message_chunk(
    connection,
    *,
    chat_ref: str,
    min_date: str | None = None,
    max_date: str | None = None,
    limit: int = 500,
    offset: int = 0,
) -> list[dict[str, Any]]:
    if limit <= 0:
        return []
    if offset < 0:
        raise ValueError("offset must be >= 0")

    where_sql, params = _cached_message_where(
        chat_ref=chat_ref,
        min_date=min_date,
        max_date=max_date,
    )
    sql = f"SELECT raw_json FROM messages WHERE {where_sql} ORDER BY date ASC, id ASC LIMIT ? OFFSET ?"
    rows = connection.execute(sql, [*params, limit, offset]).fetchall()
    return [json.loads(row["raw_json"]) for row in rows]


def load_cached_messages(
    connection,
    *,
    chat_ref: str,
    min_date: str | None = None,
    max_date: str | None = None,
) -> list[dict[str, Any]]:
    total = count_cached_messages(
        connection,
        chat_ref=chat_ref,
        min_date=min_date,
        max_date=max_date,
    )
    return load_cached_message_chunk(
        connection,
        chat_ref=chat_ref,
        min_date=min_date,
        max_date=max_date,
        limit=total,
        offset=0,
    )


def aggregate_cached_messages(
    connection,
    *,
    chat_ref: str,
    min_date: str | None = None,
    max_date: str | None = None,
    group_by: str = "day",
) -> list[dict[str, Any]]:
    lower, upper = _timestamp_bounds(min_date, max_date)
    params: list[Any] = [chat_ref]
    where = ["chat_ref = ?"]
    if lower is not None:
        where.append("date >= ?")
        params.append(lower)
    if upper is not None:
        where.append("date <= ?")
        params.append(upper)

    if group_by == "day":
        rows = connection.execute(
            f"""
            SELECT strftime('%Y-%m-%d', date, 'unixepoch') AS bucket, COUNT(*) AS count
            FROM messages
            WHERE {' AND '.join(where)}
            GROUP BY bucket
            ORDER BY bucket
            """,
            params,
        ).fetchall()
        return [{"bucket": row["bucket"], "count": row["count"]} for row in rows]

    if group_by == "week":
        rows = connection.execute(
            f"""
            SELECT strftime('%Y-W%W', date, 'unixepoch') AS bucket, COUNT(*) AS count
            FROM messages
            WHERE {' AND '.join(where)}
            GROUP BY bucket
            ORDER BY bucket
            """,
            params,
        ).fetchall()
        return [{"bucket": row["bucket"], "count": row["count"]} for row in rows]

    if group_by == "sender":
        rows = connection.execute(
            f"""
            SELECT sender_ref, MAX(sender_name) AS sender_name, COUNT(*) AS count
            FROM messages
            WHERE {' AND '.join(where)}
            GROUP BY sender_ref
            ORDER BY count DESC, sender_name
            """,
            params,
        ).fetchall()
        return [
            {
                "sender_ref": row["sender_ref"],
                "sender_name": row["sender_name"],
                "count": row["count"],
            }
            for row in rows
        ]

    raise ValueError(f"Unsupported group_by value: {group_by}")


def cache_status(connection) -> dict[str, Any]:
    path = cache_db_path()
    rows = connection.execute(
        """
        SELECT
          chat_sync_state.chat_ref,
          chat_sync_state.max_cached_id,
          chat_sync_state.last_synced_at,
          COUNT(messages.id) AS message_count
        FROM chat_sync_state
        LEFT JOIN messages ON messages.chat_ref = chat_sync_state.chat_ref
        GROUP BY chat_sync_state.chat_ref, chat_sync_state.max_cached_id, chat_sync_state.last_synced_at
        ORDER BY chat_sync_state.last_synced_at DESC
        """
    ).fetchall()

    chats = [
        {
            "chat_ref": row["chat_ref"],
            "max_cached_id": row["max_cached_id"],
            "last_synced_at": to_iso(datetime.fromtimestamp(row["last_synced_at"], tz=UTC)),
            "message_count": row["message_count"],
        }
        for row in rows
    ]
    return {
        "cache_path": str(path),
        "cache_exists": path.exists(),
        "db_size_bytes": path.stat().st_size if path.exists() else 0,
        "encryption_enabled": cache_encryption_enabled(),
        "chat_count": len(chats),
        "chats": chats,
    }
