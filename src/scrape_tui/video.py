from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from shutil import which
from typing import Any, Iterable

from rich.progress import (
    BarColumn,
    DownloadColumn,
    Progress,
    TaskID,
    TextColumn,
    TimeRemainingColumn,
    TransferSpeedColumn,
)

from .errors import DownloadFailedError, UnsupportedUrlError


@dataclass(frozen=True)
class VideoOption:
    label: str
    format_selector: str
    height: int | None = None


def ffmpeg_is_available() -> bool:
    return which("ffmpeg") is not None


def _extract_heights(
    formats: Iterable[dict[str, Any]],
    *,
    require_audio_video_single_file: bool,
) -> list[int]:
    heights: set[int] = set()
    for fmt in formats:
        height = fmt.get("height")
        if not isinstance(height, int):
            continue
        vcodec = fmt.get("vcodec")
        acodec = fmt.get("acodec")
        if vcodec in (None, "none"):
            continue
        if require_audio_video_single_file and (acodec in (None, "none")):
            continue
        heights.add(height)
    return sorted(heights, reverse=True)


def build_video_options(info: dict[str, Any]) -> list[VideoOption]:
    formats = info.get("formats") or []
    if not isinstance(formats, list):
        formats = []

    can_merge = ffmpeg_is_available()
    heights = _extract_heights(
        formats,
        require_audio_video_single_file=not can_merge,
    )

    options: list[VideoOption] = []
    if can_merge:
        options.append(
            VideoOption(
                label="Best available (requires ffmpeg for high res)",
                format_selector="bestvideo+bestaudio/best",
            )
        )
        for h in heights:
            options.append(
                VideoOption(
                    label=f"{h}p",
                    height=h,
                    format_selector=f"bestvideo[height<={h}]+bestaudio/best",
                )
            )
        options.append(VideoOption(label="Audio only", format_selector="bestaudio/best"))
        return options

    options.append(VideoOption(label="Best available (no ffmpeg detected)", format_selector="best"))
    for h in heights:
        options.append(
            VideoOption(
                label=f"{h}p (single file)",
                height=h,
                format_selector=f"best[height<={h}]",
            )
        )
    return options


def probe_with_ytdlp(url: str) -> dict[str, Any]:
    try:
        from yt_dlp import YoutubeDL
        from yt_dlp.utils import DownloadError
    except Exception as e:  # pragma: no cover
        raise DownloadFailedError("yt-dlp is not installed") from e

    try:
        with YoutubeDL(
            {
                "quiet": True,
                "no_warnings": True,
                "skip_download": True,
            }
        ) as ydl:
            return ydl.extract_info(url, download=False)
    except DownloadError as e:
        message = str(e)
        if "Unsupported URL" in message:
            raise UnsupportedUrlError(url, message=message) from e
        raise DownloadFailedError(message) from e


class _YtDlpRichProgress:
    def __init__(self, progress: Progress, *, description: str) -> None:
        self._progress = progress
        self._description = description
        self._task_id: TaskID | None = None
        self._last_total: int | None = None

    def hook(self, data: dict[str, Any]) -> None:
        status = data.get("status")
        if status == "downloading":
            downloaded = int(data.get("downloaded_bytes") or 0)
            total = data.get("total_bytes") or data.get("total_bytes_estimate")
            total_int = int(total) if isinstance(total, (int, float)) else None
            self._last_total = total_int

            if self._task_id is None:
                self._task_id = self._progress.add_task(self._description, total=total_int)

            self._progress.update(self._task_id, completed=downloaded, total=total_int)
        elif status == "finished":
            if self._task_id is not None:
                if self._last_total is not None:
                    self._progress.update(self._task_id, completed=self._last_total)


def download_with_ytdlp(
    url: str,
    *,
    output_dir: Path,
    format_selector: str,
    title: str = "Downloading",
) -> None:
    try:
        from yt_dlp import YoutubeDL
        from yt_dlp.utils import DownloadError
    except Exception as e:  # pragma: no cover
        raise DownloadFailedError("yt-dlp is not installed") from e

    output_dir.mkdir(parents=True, exist_ok=True)

    with Progress(
        TextColumn("{task.description}"),
        BarColumn(),
        DownloadColumn(),
        TransferSpeedColumn(),
        TimeRemainingColumn(),
    ) as progress:
        hook = _YtDlpRichProgress(progress, description=title)
        ydl_opts = {
            "format": format_selector,
            "quiet": True,
            "no_warnings": True,
            "progress_hooks": [hook.hook],
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
            raise DownloadFailedError(str(e)) from e
