from __future__ import annotations

from codex_telegram.tools.extras import _draft_items


def test_draft_items_accepts_list_none_and_singleton():
    sentinel = object()
    assert _draft_items([1, 2]) == [1, 2]
    assert _draft_items(None) == []
    assert _draft_items(sentinel) == [sentinel]
