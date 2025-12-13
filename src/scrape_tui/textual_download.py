from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from time import monotonic
from typing import Any, Callable
from urllib.parse import urlparse

import requests

from .errors import DownloadFailedError, UnsupportedUrlError
from .images import DEFAULT_HEADERS, ImageItem, extract_image_items
from .utils import ensure_unique_path, sanitize_filename
from .video import probe_with_ytdlp


def is_video_info(info: dict[str, Any]) -> bool:
    entries = info.get("entries")
    if isinstance(entries, list) and entries:
        return True

    formats = info.get("formats")
    if not isinstance(formats, list):
        formats = []
    for fmt in formats:
        if not isinstance(fmt, dict):
            continue
        if fmt.get("vcodec") not in (None, "none"):
            return True
    vcodec = info.get("vcodec")
    if vcodec not in (None, "none"):
        return True
    ext = info.get("ext")
    if isinstance(ext, str) and ext.lower() in {"mp4", "mkv", "webm", "mov", "m4v", "flv", "avi"}:
        return True
    return False


def _looks_like_direct_image(url: str) -> bool:
    path = urlparse(url).path.lower()
    return any(path.endswith(ext) for ext in (".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".svg"))


def _extension_from_content_type(content_type: str | None) -> str | None:
    if not content_type:
        return None
    content_type = content_type.split(";", 1)[0].strip().lower()
    if not content_type.startswith("image/"):
        return None
    subtype = content_type.split("/", 1)[1]
    if subtype in {"jpeg", "jpg"}:
        return ".jpg"
    if subtype in {"png", "gif", "webp", "bmp", "svg+xml"}:
        return "." + ("svg" if subtype == "svg+xml" else subtype)
    return None


def _fmt_bytes(n: int) -> str:
    units = ["B", "KB", "MB", "GB", "TB"]
    value = float(n)
    for u in units:
        if value < 1024 or u == units[-1]:
            return f"{value:.1f}{u}" if u != "B" else f"{int(value)}B"
        value /= 1024.0
    return f"{value:.1f}TB"


def _download_one(
    session: requests.Session,
    item: ImageItem,
    *,
    output_dir: Path,
    on_status: Callable[[str], None] | None,
    prefix: str = "",
) -> Path:
    with session.get(item.url, headers=DEFAULT_HEADERS, stream=True, timeout=30) as resp:
        resp.raise_for_status()
        ext = Path(urlparse(resp.url).path).suffix
        if not ext:
            ext = _extension_from_content_type(resp.headers.get("content-type")) or ""

        name = Path(item.filename_hint).stem
        filename = sanitize_filename(name) + ext
        dest = ensure_unique_path(output_dir / filename)

        total_header = resp.headers.get("content-length")
        total = int(total_header) if total_header and total_header.isdigit() else None

        downloaded = 0
        last_emit = 0.0
        last_pct = -1

        with dest.open("wb") as f:
            for chunk in resp.iter_content(chunk_size=1024 * 128):
                if not chunk:
                    continue
                f.write(chunk)
                downloaded += len(chunk)

                if on_status is None:
                    continue

                now = monotonic()
                if now - last_emit < 0.1:
                    continue
                last_emit = now

                if total:
                    pct = int(downloaded * 100 / max(1, total))
                    if pct == last_pct:
                        continue
                    last_pct = pct
                    on_status(f"{prefix}{dest.name} {pct}% ({_fmt_bytes(downloaded)}/{_fmt_bytes(total)})")
                else:
                    on_status(f"{prefix}{dest.name} {_fmt_bytes(downloaded)}")

        if on_status is not None:
            on_status(f"{prefix}{dest.name} done")
        return dest


def download_images_from_url_textual(
    url: str,
    *,
    output_dir: Path,
    max_images: int | None = None,
    on_status: Callable[[str], None] | None = None,
) -> list[Path]:
    output_dir.mkdir(parents=True, exist_ok=True)

    session = requests.Session()
    session.headers.update(DEFAULT_HEADERS)

    downloaded: list[Path] = []

    if _looks_like_direct_image(url):
        downloaded.append(
            _download_one(
                session,
                ImageItem(url=url, filename_hint="image"),
                output_dir=output_dir,
                on_status=on_status,
            )
        )
        return downloaded

    try:
        resp = session.get(url, timeout=30)
        resp.raise_for_status()
    except requests.RequestException as e:
        raise DownloadFailedError(str(e)) from e

    content_type = (resp.headers.get("content-type") or "").lower()
    if content_type.startswith("image/"):
        downloaded.append(
            _download_one(
                session,
                ImageItem(url=resp.url, filename_hint="image"),
                output_dir=output_dir,
                on_status=on_status,
            )
        )
        return downloaded

    if "text/html" not in content_type and "<html" not in resp.text.lower():
        raise DownloadFailedError(f"URL did not look like HTML or an image: {url}")

    items = extract_image_items(resp.text, base_url=resp.url)
    if not items:
        raise DownloadFailedError("No images found on the page")

    if max_images is not None:
        items = items[: max(0, max_images)]

    total = len(items)
    for idx, item in enumerate(items, start=1):
        prefix = f"[{idx}/{total}] "
        try:
            if on_status is not None:
                on_status(f"{prefix}downloading…")
            downloaded.append(
                _download_one(
                    session,
                    item,
                    output_dir=output_dir,
                    on_status=on_status,
                    prefix=prefix,
                )
            )
        except requests.RequestException:
            continue

    if not downloaded:
        raise DownloadFailedError("Failed to download any images")
    return downloaded


def download_with_ytdlp_textual(
    url: str,
    *,
    output_dir: Path,
    format_selector: str,
    on_status: Callable[[str], None] | None = None,
) -> None:
    try:
        from yt_dlp import YoutubeDL
        from yt_dlp.utils import DownloadError
    except Exception as e:  # pragma: no cover
        raise DownloadFailedError("yt-dlp is not installed") from e

    output_dir.mkdir(parents=True, exist_ok=True)

    last_emit = 0.0
    last_pct = -1

    def hook(data: dict[str, Any]) -> None:
        nonlocal last_emit, last_pct
        if on_status is None:
            return

        status = data.get("status")
        if status == "downloading":
            downloaded = int(data.get("downloaded_bytes") or 0)
            total = data.get("total_bytes") or data.get("total_bytes_estimate")
            total_int = int(total) if isinstance(total, (int, float)) else None

            now = monotonic()
            if now - last_emit < 0.1:
                return
            last_emit = now

            if total_int:
                pct = int(downloaded * 100 / max(1, total_int))
                if pct == last_pct:
                    return
                last_pct = pct
                on_status(f"video {pct}% ({_fmt_bytes(downloaded)}/{_fmt_bytes(total_int)})")
            else:
                on_status(f"video {_fmt_bytes(downloaded)}")
        elif status == "finished":
            on_status("video finished, finalizing…")

    ydl_opts = {
        "format": format_selector,
        "quiet": True,
        "no_warnings": True,
        "progress_hooks": [hook],
        "retries": 3,
        "outtmpl": {
            "default": str(output_dir / "%(title)s.%(ext)s"),
            "playlist": str(output_dir / "%(playlist_title)s" / "%(title)s.%(ext)s"),
        },
        "windowsfilenames": True,
    }

    try:
        with YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])
    except DownloadError as e:
        message = str(e)
        if "Unsupported URL" in message:
            raise UnsupportedUrlError(url, message=message) from e
        raise DownloadFailedError(message) from e

