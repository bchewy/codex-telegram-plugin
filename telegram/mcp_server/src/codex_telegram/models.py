from __future__ import annotations

from dataclasses import asdict, dataclass, fields
import json


@dataclass(slots=True)
class StoredSession:
    api_id: int
    api_hash: str
    session_string: str
    phone: str | None = None
    user_id: int | None = None
    username: str | None = None
    display_name: str | None = None
    created_at: str | None = None
    updated_at: str | None = None

    def to_json(self) -> str:
        return json.dumps(asdict(self), sort_keys=True)

    @classmethod
    def from_json(cls, raw: str) -> "StoredSession":
        data = json.loads(raw)
        if not isinstance(data, dict):
            raise ValueError("Stored session payload must be a JSON object.")
        # Ignore unknown keys so payloads written by a newer plugin version
        # still load instead of crashing cls(**data).
        known = {field.name for field in fields(cls)}
        return cls(**{key: value for key, value in data.items() if key in known})
