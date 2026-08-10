"""Shared helpers for all store scrapers.

Kept dependency-free (standard library only) so the proof-of-concept runs
without installing anything. We can swap urllib for `requests` later.
"""
from __future__ import annotations

import gzip
import json
import os
import re
import time
import urllib.request
from datetime import datetime, timezone

# A realistic browser User-Agent. Some sites answer differently (or block)
# requests that look like bots, so we present ourselves like a normal browser.
DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "ru,en;q=0.9,uz;q=0.8",
    "Accept-Encoding": "gzip",
}

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")


def http_get_json(url: str, headers: dict | None = None, timeout: int = 30) -> dict:
    """GET a URL and parse the JSON body. Handles gzip responses."""
    req = urllib.request.Request(url, headers={**DEFAULT_HEADERS, **(headers or {})})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read()
        if resp.headers.get("Content-Encoding") == "gzip":
            raw = gzip.decompress(raw)
    return json.loads(raw.decode("utf-8"))


def parse_price(value) -> int | None:
    """Turn a price like "19 990", "19 990 so'm" or 19990 into an int (19990)."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return int(value)
    digits = re.sub(r"[^\d]", "", str(value))
    return int(digits) if digits else None


def parse_percent(value) -> int | None:
    """Turn "-33%" / "33%" / 33 into 33."""
    if value is None:
        return None
    m = re.search(r"\d+", str(value))
    return int(m.group()) if m else None


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def save_json(filename: str, payload) -> str:
    """Write `payload` as pretty JSON into the data/ directory. Returns the path."""
    os.makedirs(DATA_DIR, exist_ok=True)
    path = os.path.join(DATA_DIR, filename)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    return path


def polite_sleep(seconds: float = 1.0) -> None:
    """Small pause between requests so we don't hammer a store's servers."""
    time.sleep(seconds)
