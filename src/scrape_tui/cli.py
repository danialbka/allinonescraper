from __future__ import annotations

import argparse
from datetime import datetime
import os
from pathlib import Path
import sys
from typing import Any

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm, IntPrompt
from rich.table import Table

from .autofix import offer_codex_autofix
from .errors import DownloadFailedError, UnsupportedUrlError
from .images import download_images_from_url
from .utils import domain_from_url, sanitize_filename
from .video import build_video_options, download_with_ytdlp, probe_with_ytdlp


def _is_video_info(info: dict[str, Any]) -> bool:
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


def _pick_video_option(console: Console, options) -> int:
    table = Table(title="Video download options", show_lines=True)
    table.add_column("#", style="bold cyan", justify="right")
    table.add_column("Quality", style="bold")
    table.add_column("Format selector", overflow="fold")

    for idx, opt in enumerate(options, start=1):
        table.add_row(str(idx), opt.label, opt.format_selector)

    console.print(table)
    choice = IntPrompt.ask("Choose an option", default=1)
    if choice < 1 or choice > len(options):
        raise DownloadFailedError("Invalid selection")
    return choice - 1


def _error_panel(message: str) -> Panel:
    hint = "\n".join(
        [
            "[bold]Troubleshooting[/bold]",
            "- Try updating yt-dlp: `python3 -m pip install -U yt-dlp`",
            "- Install ffmpeg for high-res merges",
            "- Some sites require login/cookies",
            "",
            "[bold]Codex CLI (developer assist)[/bold]",
            "- Headless login: `codex login --device-auth`",
            "- On errors, you can run an in-app Codex auto-fix (source checkout only)",
        ]
    )
    return Panel(f"[red]{message}[/red]\n\n{hint}", title="Error", border_style="red")


def _restart_self() -> None:
    os.execv(sys.executable, [sys.executable, "-m", "scrape_tui", *sys.argv[1:]])


def _pause(console: Console, message: str = "Press Enter to return to the main menu...") -> None:
    console.input(f"\n{message}")


def _ask_download_mode(console: Console, *, default_mode: str) -> str:
    mapping = {
        "a": "auto",
        "auto": "auto",
        "v": "video",
        "video": "video",
        "i": "images",
        "img": "images",
        "image": "images",
        "images": "images",
        "pic": "images",
        "pics": "images",
        "picture": "images",
        "pictures": "images",
    }
    default_token = {"auto": "a", "video": "v", "images": "i"}.get(default_mode, "a")
    while True:
        raw = console.input(f"Download [a]uto / [v]ideo / [i]mages (default {default_token}): ").strip().lower()
        if not raw:
            return default_mode
        mode = mapping.get(raw)
        if mode:
            return mode
        console.print("[red]Invalid choice.[/red]")


def _download_once(console: Console, *, url: str, args, mode: str, interactive: bool) -> int:
    domain = sanitize_filename(domain_from_url(url))
    session = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_dir = args.output / domain / session

    if mode in {"auto", "video"}:
        try:
            info = probe_with_ytdlp(url)
            if _is_video_info(info) or mode == "video":
                title = info.get("title") or "video"
                panel_title = "Detected video" if _is_video_info(info) else "Video download"
                console.print(Panel(f"[bold]{title}[/bold]", title=panel_title, border_style="green"))

                options = build_video_options(info)
                selected = options[_pick_video_option(console, options)]
                download_with_ytdlp(
                    url,
                    output_dir=output_dir,
                    format_selector=selected.format_selector,
                    title=f"Downloading ({selected.label})",
                )
                console.print(f"[green]Saved to[/green] {output_dir}")
                return 0
        except UnsupportedUrlError:
            if mode == "video":
                raise
        except DownloadFailedError:
            if mode == "video":
                raise
            if interactive and not Confirm.ask("Video download failed. Try images instead?", default=True):
                raise

    if mode in {"auto", "images"}:
        paths = download_images_from_url(url, output_dir=output_dir, max_images=args.max_images)
        console.print(f"[green]Downloaded {len(paths)} image(s) to[/green] {output_dir}")
        return 0

    raise DownloadFailedError("No downloader matched the requested mode.")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="allinonescraper",
        description="All-in-one downloader TUI (videos + images).",
    )
    parser.add_argument("url", nargs="?", help="URL to download")
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=Path("downloads"),
        help="Base output directory (default: ./downloads)",
    )
    parser.add_argument(
        "--mode",
        choices=["auto", "video", "images"],
        default="auto",
        help="Force download mode (default: auto)",
    )
    parser.add_argument("--max-images", type=int, default=None, help="Limit images when scraping a page")
    parser.add_argument("--no-codex", action="store_true", help="Disable Codex auto-fix prompts on errors")
    args = parser.parse_args(argv)

    console = Console()
    initial_url = (args.url or "").strip() or None
    loop = initial_url is None and sys.stdin.isatty()

    last_exit_code = 0
    while True:
        console.clear()
        console.print(
            Panel.fit(
                "[bold]allinonescraper[/bold]\n"
                f"Default mode: [bold]{args.mode}[/bold] | Output: [bold]{args.output}[/bold]\n"
                "Paste a URL to download (blank to quit).",
                border_style="cyan",
            )
        )

        url = initial_url
        if url is None:
            url = console.input("URL (blank to quit): ").strip() or None

        if not url:
            return last_exit_code

        mode = args.mode
        if loop and args.mode == "auto":
            mode = _ask_download_mode(console, default_mode=args.mode)

        try:
            last_exit_code = _download_once(console, url=url, args=args, mode=mode, interactive=loop)
        except UnsupportedUrlError:
            last_exit_code = 1
            console.print(_error_panel("This URL is not supported for video download."))
            if not args.no_codex:
                applied = offer_codex_autofix(console, url=url, error="Unsupported URL for video download")
                if applied and Confirm.ask("Restart now to use the patch?", default=True):
                    _restart_self()
        except DownloadFailedError as e:
            last_exit_code = 1
            console.print(_error_panel(str(e)))
            if not args.no_codex:
                applied = offer_codex_autofix(console, url=url, error=str(e))
                if applied and Confirm.ask("Restart now to use the patch?", default=True):
                    _restart_self()

        if not loop:
            return last_exit_code

        initial_url = None
        _pause(console)
