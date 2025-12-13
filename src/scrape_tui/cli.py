from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.panel import Panel
from rich.prompt import IntPrompt, Prompt
from rich.table import Table

from .autofix import offer_codex_autofix
from .errors import DownloadFailedError, UnsupportedUrlError
from .images import download_images_from_url
from .utils import domain_from_url, sanitize_filename
from .video import build_video_options, download_with_ytdlp, probe_with_ytdlp


def _is_video_info(info: dict[str, Any]) -> bool:
    formats = info.get("formats")
    if not isinstance(formats, list):
        return False
    for fmt in formats:
        if not isinstance(fmt, dict):
            continue
        if fmt.get("vcodec") not in (None, "none"):
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
            "- Or run with `--codex-autofix` to attempt an automated patch (source checkout only)",
        ]
    )
    return Panel(f"[red]{message}[/red]\n\n{hint}", title="Error", border_style="red")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="scrape", description="All-in-one downloader TUI (videos + images).")
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
    parser.add_argument(
        "--codex-autofix",
        action="store_true",
        help="On errors, offer to run Codex CLI to patch this repo (developer mode)",
    )
    args = parser.parse_args(argv)

    console = Console()
    console.print(Panel.fit("[bold]scrape-tui[/bold]\nPaste a URL to download.", border_style="cyan"))

    url = (args.url or "").strip()
    if not url:
        url = Prompt.ask("URL").strip()
    if not url:
        console.print(_error_panel("No URL provided."))
        return 2

    domain = sanitize_filename(domain_from_url(url))
    session = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_dir = args.output / domain / session

    if args.mode in {"auto", "video"}:
        try:
            info = probe_with_ytdlp(url)
            if _is_video_info(info):
                title = info.get("title") or "video"
                console.print(Panel(f"[bold]{title}[/bold]", title="Detected video", border_style="green"))

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
            if args.mode == "video":
                console.print(_error_panel("This URL is not supported for video download."))
                if args.codex_autofix:
                    offer_codex_autofix(console, url=url, error="Unsupported URL for video download")
                return 1
        except DownloadFailedError as e:
            if args.mode == "video":
                console.print(_error_panel(str(e)))
                if args.codex_autofix:
                    offer_codex_autofix(console, url=url, error=str(e))
                return 1

    if args.mode in {"auto", "images"}:
        try:
            paths = download_images_from_url(url, output_dir=output_dir, max_images=args.max_images)
            console.print(f"[green]Downloaded {len(paths)} image(s) to[/green] {output_dir}")
            return 0
        except DownloadFailedError as e:
            console.print(_error_panel(str(e)))
            if args.codex_autofix:
                offer_codex_autofix(console, url=url, error=str(e))
            return 1

    console.print(_error_panel("No downloader matched the requested mode."))
    return 1
