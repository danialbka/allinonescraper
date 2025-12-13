from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from rich.progress import (
    BarColumn,
    DownloadColumn,
    Progress,
    TextColumn,
    TimeRemainingColumn,
    TransferSpeedColumn,
    track,
)

from .errors import DownloadFailedError
from .utils import ensure_unique_path, sanitize_filename


DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )
}


IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".svg"}


@dataclass(frozen=True)
class ImageItem:
    url: str
    filename_hint: str


def _is_data_url(url: str) -> bool:
    return url.strip().lower().startswith("data:")


def _looks_like_direct_image(url: str) -> bool:
    path = urlparse(url).path.lower()
    return any(path.endswith(ext) for ext in IMAGE_EXTENSIONS)


def _parse_srcset(srcset: str) -> str | None:
    candidates: list[tuple[float, str]] = []
    for part in srcset.split(","):
        chunk = part.strip()
        if not chunk:
            continue
        bits = chunk.split()
        candidate_url = bits[0]
        score = 0.0
        if len(bits) > 1:
            desc = bits[1]
            try:
                if desc.endswith("w"):
                    score = float(int(desc[:-1]))
                elif desc.endswith("x"):
                    score = float(desc[:-1])
            except ValueError:
                score = 0.0
        candidates.append((score, candidate_url))
    if not candidates:
        return None
    candidates.sort(key=lambda x: x[0], reverse=True)
    return candidates[0][1]


def _best_img_source(tag) -> str | None:
    for attr in ("srcset", "data-srcset"):
        srcset = tag.get(attr)
        if isinstance(srcset, str):
            best = _parse_srcset(srcset)
            if best:
                return best
    for attr in ("src", "data-src", "data-original", "data-lazy-src"):
        src = tag.get(attr)
        if isinstance(src, str) and src.strip():
            return src
    return None


def extract_image_items(html: str, *, base_url: str) -> list[ImageItem]:
    soup = BeautifulSoup(html, "html.parser")

    base_tag = soup.find("base", href=True)
    if base_tag and isinstance(base_tag.get("href"), str):
        base_url = urljoin(base_url, base_tag["href"])

    urls: list[str] = []

    meta = soup.find("meta", attrs={"property": "og:image"})
    if meta and isinstance(meta.get("content"), str):
        urls.append(meta["content"])

    link_image_src = soup.find("link", attrs={"rel": "image_src"})
    if link_image_src and isinstance(link_image_src.get("href"), str):
        urls.append(link_image_src["href"])

    for img in soup.find_all("img"):
        src = _best_img_source(img)
        if src:
            urls.append(src)

    seen: set[str] = set()
    items: list[ImageItem] = []
    for raw in urls:
        if _is_data_url(raw):
            continue
        absolute = urljoin(base_url, raw)
        if absolute in seen:
            continue
        seen.add(absolute)
        hint = Path(urlparse(absolute).path).name or "image"
        items.append(ImageItem(url=absolute, filename_hint=hint))

    return items


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


def _download_one(session: requests.Session, item: ImageItem, *, output_dir: Path) -> Path:
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

        with Progress(
            TextColumn("{task.description}"),
            BarColumn(),
            DownloadColumn(),
            TransferSpeedColumn(),
            TimeRemainingColumn(),
            transient=True,
        ) as progress:
            task_id = progress.add_task(dest.name, total=total)
            with dest.open("wb") as f:
                for chunk in resp.iter_content(chunk_size=1024 * 128):
                    if not chunk:
                        continue
                    f.write(chunk)
                    progress.update(task_id, advance=len(chunk))
        return dest


def download_images_from_url(
    url: str,
    *,
    output_dir: Path,
    max_images: int | None = None,
) -> list[Path]:
    output_dir.mkdir(parents=True, exist_ok=True)

    session = requests.Session()
    session.headers.update(DEFAULT_HEADERS)

    downloaded: list[Path] = []

    if _looks_like_direct_image(url):
        downloaded.append(_download_one(session, ImageItem(url=url, filename_hint="image"), output_dir=output_dir))
        return downloaded

    try:
        resp = session.get(url, timeout=30)
        resp.raise_for_status()
    except requests.RequestException as e:
        raise DownloadFailedError(str(e)) from e

    content_type = (resp.headers.get("content-type") or "").lower()
    if content_type.startswith("image/"):
        downloaded.append(
            _download_one(session, ImageItem(url=resp.url, filename_hint="image"), output_dir=output_dir)
        )
        return downloaded

    if "text/html" not in content_type and "<html" not in resp.text.lower():
        raise DownloadFailedError(f"URL did not look like HTML or an image: {url}")

    items = extract_image_items(resp.text, base_url=resp.url)
    if not items:
        raise DownloadFailedError("No images found on the page")

    if max_images is not None:
        items = items[: max(0, max_images)]

    for item in track(items, description="Downloading images"):
        try:
            downloaded.append(_download_one(session, item, output_dir=output_dir))
        except requests.RequestException:
            continue

    if not downloaded:
        raise DownloadFailedError("Failed to download any images")
    return downloaded

