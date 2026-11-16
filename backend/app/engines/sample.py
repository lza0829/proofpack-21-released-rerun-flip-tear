from __future__ import annotations

import hashlib
import math
from typing import Any


def _bucket(seed: str, business_key: str) -> float:
    """Deterministic 0..1 bucket from seed + key."""
    digest = hashlib.sha256(f"{seed}|{business_key}".encode("utf-8")).hexdigest()
    # use first 12 hex chars -> int -> [0, 1)
    n = int(digest[:12], 16)
    return n / float(16**12)


def sample_items(
    items: list[dict[str, Any]],
    rate: float,
    seed: str,
) -> list[dict[str, Any]]:
    """
    Deterministic sampling by seed.
    Items whose bucket < rate are included; sorted by business_key for stability.
    Ensures at least one item when source is non-empty and rate > 0.
    """
    if not items:
        return []
    rate = max(0.0, min(1.0, float(rate)))
    if rate <= 0:
        return []
    if rate >= 1.0:
        return sorted(items, key=lambda x: str(x.get("business_key", "")))

    selected = [
        item
        for item in items
        if _bucket(seed, str(item.get("business_key", ""))) < rate
    ]
    if not selected and items:
        # fallback: take ceil(rate * n) by bucket order for reproducibility
        ranked = sorted(
            items,
            key=lambda x: (_bucket(seed, str(x.get("business_key", ""))), str(x.get("business_key", ""))),
        )
        n = max(1, min(len(items), math.ceil(rate * len(items))))
        selected = ranked[:n]
    return sorted(selected, key=lambda x: str(x.get("business_key", "")))
