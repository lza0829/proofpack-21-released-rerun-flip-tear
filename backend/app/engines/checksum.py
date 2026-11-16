from __future__ import annotations

import hashlib
import json
from typing import Any


def item_fingerprint(item: dict[str, Any]) -> str:
    payload = {
        "business_key": item.get("business_key"),
        "amount": item.get("amount"),
        "qty": item.get("qty"),
        "event_ts": item.get("event_ts"),
        "revision": item.get("revision"),
        "title": item.get("title"),
    }
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def pack_fingerprint(items: list[dict[str, Any]]) -> str:
    """SHA256 over sorted item fingerprints (by business_key)."""
    sorted_items = sorted(items, key=lambda x: str(x.get("business_key", "")))
    digests = [item_fingerprint(it) for it in sorted_items]
    joined = "\n".join(digests)
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()
