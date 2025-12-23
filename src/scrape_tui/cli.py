from __future__ import annotations

import argparse
from datetime import datetime
import os
from pathlib import Path
import sys
from typing import Any

from rich import box
from rich.console import Console
from rich.prompt import Confirm, IntPrompt
from rich.table import Table

from .autofix import offer_codex_autofix
from .errors import DownloadFailedError, UnsupportedUrlError
from .images import download_images_from_url
from .utils import domain_from_url, sanitize_filename
from .video import build_video_options, download_with_ytdlp, probe_with_ytdlp


def _enable_readline_shortcuts() -> None:
    try:
        import readline  # noqa: F401
    except Exception:
        return

    if not sys.stdin.isatty():
        return

    try:
        import readline

        for binding in (
            r'"\e[127;5u": backward-kill-word',  # xterm modifyOtherKeys
            r'"\e[8;5u": backward-kill-word',  # kitty keyboard protocol
        ):
            try:
                readline.parse_and_bind(binding)
            except Exception:
                pass

        try:
            import termios

            cc = termios.tcgetattr(sys.stdin.fileno())[6]
            erase = cc[termios.VERASE]
            if isinstance(erase, int) and erase == 0x7F:
                readline.parse_and_bind(r'"\C-h": backward-kill-word')
        except Exception:
            pass
    except Exception:
        return


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
    table = Table(title="Video download options", box=box.SIMPLE)
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


def _error_panel(message: str) -> Table:
    table = Table(title="Error", box=box.SIMPLE, border_style="red", show_header=False)
    table.add_column("Details", style="red")
    table.add_row(message)
    table.add_row("")
    table.add_row("Troubleshooting")
    table.add_row("- Try updating yt-dlp: `python3 -m pip install -U yt-dlp`")
    table.add_row("- Install ffmpeg for high-res merges")
    table.add_row("- Some sites require login/cookies")
    table.add_row("")
    table.add_row("Codex CLI (developer assist)")
    table.add_row("- Headless login: `codex login --device-auth`")
    table.add_row("- On errors, you can run an in-app Codex auto-fix (source checkout only)")
    return table


def _restart_self() -> None:
    os.execv(sys.executable, [sys.executable, "-m", "scrape_tui", *sys.argv[1:]])


def _pause(console: Console, message: str = "Press Enter to return to the main menu...") -> None:
    try:
        input(f"\n{message}")
    except EOFError:
        return


def _print_guide(console: Console) -> None:
    guide = Table(title="Help", box=box.SIMPLE, show_header=False)
    guide.add_column("Tips")
    guide.add_row("Paste a URL and press Enter (blank URL exits)")
    guide.add_row("Choose (v)ideo to force video, (i)mages to force images, or (a)uto")
    guide.add_row("Video: pick a quality number; installing `ffmpeg` enables best-quality merges")
    guide.add_row("Output: `downloads/<domain>/<timestamp>/` (change with `--output`)")
    guide.add_row("")
    guide.add_row("Line editing: Ctrl+Backspace / Ctrl+W delete word, Ctrl+U clears line")
    console.print(guide)


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
        try:
            raw = input(f"Download (a)uto / (v)ideo / (i)mages (default {default_token}): ").strip().lower()
        except EOFError:
            return default_mode
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
                title_table = Table(
                    title="Detected video" if _is_video_info(info) else "Video download",
                    box=box.SIMPLE,
                    border_style="green",
                    show_header=False,
                )
                title_table.add_column("Title", style="green")
                title_table.add_row(title)
                console.print(title_table)

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
    _enable_readline_shortcuts()

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

    initial_url = (args.url or "").strip() or None
    loop = initial_url is None and sys.stdin.isatty()

    console = Console()

    last_exit_code = 0
    while True:
        console.clear()
        header = Table(title="allinonescraper", box=box.SIMPLE, show_header=False)
        header.add_column("Session")
        header.add_row(f"Default mode: {args.mode} | Output: {args.output}")
        header.add_row("Paste a URL to download (blank to quit).")
        console.print(header)
        _print_guide(console)

        url = initial_url
        if url is None:
            try:
                url = input("URL (blank to quit): ").strip() or None
            except EOFError:
                return last_exit_code

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
