from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import urlparse


_INVALID_CHARS = re.compile(r"[^\w.\- ]+", flags=re.UNICODE)
_WHITESPACE = re.compile(r"\s+")


def sanitize_filename(name: str, *, max_length: int = 180) -> str:
    cleaned = _INVALID_CHARS.sub("_", name).strip(" .")
    cleaned = _WHITESPACE.sub(" ", cleaned).strip()
    if not cleaned:
        cleaned = "download"
    return cleaned[:max_length]


def ensure_unique_path(path: Path) -> Path:
    if not path.exists():
        return path
    stem = path.stem
    suffix = path.suffix
    parent = path.parent
    for i in range(1, 10_000):
        candidate = parent / f"{stem}_{i}{suffix}"
        if not candidate.exists():
            return candidate
    raise RuntimeError(f"Could not find a unique filename for: {path}")


def domain_from_url(url: str) -> str:
    parsed = urlparse(url)
    host = (parsed.hostname or "site").lower()
    return host.replace("www.", "", 1)

