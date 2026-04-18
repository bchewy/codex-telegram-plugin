from __future__ import annotations

from dataclasses import asdict, dataclass
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
        return cls(**data)
