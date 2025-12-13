from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from queue import SimpleQueue
import sys
import threading
from typing import Any, Literal

from rich.text import Text
from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Button, Footer, Header, Input, Select, Static

from .avatar_renderer import AvatarBackend
from .avatar_assets import ensure_frames_dir
from .avatar_widget import AvatarWidget
from .errors import DownloadFailedError, UnsupportedUrlError
from .settings import UiSettings, load_ui_settings, save_ui_settings
from .textual_download import (
    download_images_from_url_textual,
    download_with_ytdlp_textual,
    is_video_info,
    probe_with_ytdlp,
)
from .utils import domain_from_url, sanitize_filename
from .video import build_video_options


Mode = Literal["auto", "video", "images"]


@dataclass(frozen=True)
class ScrapeTextualArgs:
    url: str | None
    output: Path
    mode: Mode
    max_images: int | None
    frames_dir: Path
    avatar_fps: float
    avatar_backend: AvatarBackend
    avatar_width_chars: int
    avatar_height_chars: int
    theme: str | None


@dataclass(frozen=True)
class UiEvent:
    kind: Literal["status", "error", "done", "video_options"]
    message: str
    data: Any | None = None


class _Status(Static):
    def set_lines(self, lines: list[str]) -> None:
        self.update(Text("\n".join(lines)))


class ScrapeTextualApp(App[int]):
    CSS = """
    #body {
        layout: horizontal;
        height: 1fr;
    }

    #left {
        width: 1fr;
        padding: 1 2;
    }

    #avatar {
        margin: 1 2 0 0;
    }

    #controls Input {
        width: 1fr;
    }

    #controls Button {
        width: 1fr;
    }

    #log {
        border: round $surface;
        padding: 1 1;
        height: 1fr;
    }
    """

    BINDINGS = [("q", "quit", "Quit")]

    def __init__(self, args: ScrapeTextualArgs) -> None:
        super().__init__()
        self.args = args
        self._ui_settings = UiSettings(theme=args.theme)
        self._events: SimpleQueue[UiEvent] = SimpleQueue()
        self._worker: threading.Thread | None = None
        self._busy = False
        self._video_options: list[tuple[str, str]] = []
        self._video_url: str | None = None

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Horizontal(id="body"):
            with Vertical(id="left"):
                with Vertical(id="controls"):
                    yield Static("URL", classes="label")
                    yield Input(value=self.args.url or "", placeholder="https://…", id="url")
                    yield Static("Mode", classes="label")
                    yield Select(
                        options=[("auto", "auto"), ("video", "video"), ("images", "images")],
                        value=self.args.mode,
                        id="mode",
                    )
                    yield Static("Theme", classes="label")
                    yield Select(options=[], id="theme")
                    yield Static("Max images (optional)", classes="label")
                    yield Input(value="" if self.args.max_images is None else str(self.args.max_images), id="max_images")
                    yield Static("Output directory", classes="label")
                    yield Input(value=str(self.args.output), id="output")
                    yield Static("Video quality (auto-detected)", classes="label", id="video_label")
                    yield Select(options=[], id="video_quality")
                    yield Button("Start", id="start")
                yield _Status(id="log")

            yield AvatarWidget(
                id="avatar",
                frames_dir=self.args.frames_dir,
                width_chars=self.args.avatar_width_chars,
                height_chars=self.args.avatar_height_chars,
                fps=self.args.avatar_fps,
                backend=self.args.avatar_backend,
            )
        yield Footer()

    def on_mount(self) -> None:
        self._log = self.query_one("#log", _Status)
        self._url = self.query_one("#url", Input)
        self._mode = self.query_one("#mode", Select)
        self._theme = self.query_one("#theme", Select)
        self._max_images = self.query_one("#max_images", Input)
        self._output = self.query_one("#output", Input)
        self._video_label = self.query_one("#video_label", Static)
        self._video_quality = self.query_one("#video_quality", Select)
        self._video_label.display = False
        self._video_quality.display = False
        self.set_interval(0.05, self._drain_events)
        self._set_log(
            [
                "Avatar panel is active (Unicode + truecolor; no Kitty/SIXEL).",
                "Enter a URL and press Start.",
                "",
                "Controls: q to quit.",
            ]
        )

        self._init_theme_picker()

    def _set_log(self, lines: list[str]) -> None:
        self._log.set_lines(lines)

    def _init_theme_picker(self) -> None:
        themes = list(self.available_themes)
        themes.sort()
        options = [(name, name) for name in themes]
        if hasattr(self._theme, "set_options"):
            self._theme.set_options(options)  # type: ignore[attr-defined]
        else:
            self._theme.options = options  # type: ignore[assignment]

        desired = self._ui_settings.theme
        if isinstance(desired, str) and desired in themes:
            self.theme = desired
            self._theme.value = desired
        else:
            # Align picker to current theme for discoverability.
            try:
                current = str(self.theme)
            except Exception:
                current = ""
            self._theme.value = current if current in themes else (themes[0] if themes else None)

    def _set_busy(self, busy: bool) -> None:
        self._busy = busy
        for widget in (self._url, self._mode, self._theme, self._max_images, self._output, self._video_quality):
            try:
                widget.disabled = busy
            except Exception:
                pass
        self.query_one("#start", Button).disabled = busy

    def _drain_events(self) -> None:
        last: UiEvent | None = None
        while True:
            try:
                last = self._events.get_nowait()
            except Exception:
                break

        if last is None:
            return

        if last.kind == "error":
            self._set_log(["Error:", last.message])
            self._set_busy(False)
            return

        if last.kind == "done":
            self._set_log([last.message])
            self._set_busy(False)
            return

        if last.kind == "video_options":
            payload = last.data or {}
            self._video_options = list(payload.get("options") or [])
            self._video_url = payload.get("url")
            if self._video_options:
                if hasattr(self._video_quality, "set_options"):
                    self._video_quality.set_options(self._video_options)  # type: ignore[attr-defined]
                else:
                    self._video_quality.options = self._video_options  # type: ignore[assignment]
                self._video_quality.value = self._video_options[0][1]
                self._video_label.display = True
                self._video_quality.display = True
                self._set_log(
                    [
                        "Video detected.",
                        "Pick a quality, then press Start again to download.",
                    ]
                )
                self._set_busy(False)
            else:
                self._video_label.display = False
                self._video_quality.display = False
            return

        if last.kind == "status":
            self._set_log([last.message])
            return

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "start":
            if self._busy:
                return

            url = (self._url.value or "").strip()
            if not url:
                self._set_log(["Enter a URL first."])
                return

            mode = self._mode.value or "auto"
            if mode not in ("auto", "video", "images"):
                self._set_log(["Mode must be auto/video/images."])
                return

            max_images_raw = (self._max_images.value or "").strip()
            max_images = None
            if max_images_raw:
                try:
                    max_images = int(max_images_raw)
                except ValueError:
                    self._set_log(["Max images must be an integer (or blank)."])
                    return

            output_dir = Path((self._output.value or "").strip() or "downloads")

            if mode in ("auto", "video") and self._video_quality.display and self._video_url == url:
                format_selector = self._video_quality.value
                if isinstance(format_selector, str) and format_selector.strip():
                    self._start_thread(
                        self._download_video,
                        url,
                        output_dir,
                        format_selector,
                    )
                    return

            self._video_label.display = False
            self._video_quality.display = False
            self._video_url = None
            self._start_thread(self._probe_and_maybe_download, url, output_dir, mode, max_images)

    def on_select_changed(self, event: Select.Changed) -> None:
        if event.select.id != "theme":
            return
        value = event.value
        if not isinstance(value, str) or not value.strip():
            return
        if value not in self.available_themes:
            return
        self.theme = value
        self._ui_settings.theme = value
        try:
            save_ui_settings(self._ui_settings)
        except Exception:
            pass

    def _start_thread(self, target, *args) -> None:
        self._set_busy(True)
        self._worker = threading.Thread(target=target, args=args, daemon=True)
        self._worker.start()

    def _session_output_dir(self, output_base: Path, url: str) -> Path:
        domain = sanitize_filename(domain_from_url(url))
        session = datetime.now().strftime("%Y%m%d_%H%M%S")
        return output_base / domain / session

    def _probe_and_maybe_download(self, url: str, output_base: Path, mode: Mode, max_images: int | None) -> None:
        try:
            self._events.put(UiEvent(kind="status", message="Probing URL…"))
            info: dict[str, Any] | None = None
            if mode in ("auto", "video"):
                try:
                    info = probe_with_ytdlp(url)
                except UnsupportedUrlError:
                    info = None

            if mode == "video" and info is None:
                raise DownloadFailedError("This URL is not supported for video download.")

            if info is not None and (is_video_info(info) or mode == "video"):
                options = build_video_options(info)
                select_options = [(opt.label, opt.format_selector) for opt in options]
                self._events.put(
                    UiEvent(
                        kind="video_options",
                        message="video options",
                        data={"url": url, "options": select_options},
                    )
                )
                return

            self._events.put(UiEvent(kind="status", message="Downloading images…"))
            session_dir = self._session_output_dir(output_base, url)
            downloaded = download_images_from_url_textual(
                url,
                output_dir=session_dir,
                max_images=max_images,
                on_status=lambda msg: self._events.put(UiEvent(kind="status", message=msg)),
            )
            self._events.put(
                UiEvent(kind="done", message=f"Downloaded {len(downloaded)} image(s) to {session_dir}")
            )
        except Exception as e:
            self._events.put(UiEvent(kind="error", message=str(e)))

    def _download_video(self, url: str, output_base: Path, format_selector: str) -> None:
        try:
            self._events.put(UiEvent(kind="status", message="Downloading video…"))
            session_dir = self._session_output_dir(output_base, url)
            download_with_ytdlp_textual(
                url,
                output_dir=session_dir,
                format_selector=format_selector,
                on_status=lambda msg: self._events.put(UiEvent(kind="status", message=msg)),
            )
            self._events.put(UiEvent(kind="done", message=f"Saved video to {session_dir}"))
        except Exception as e:
            self._events.put(UiEvent(kind="error", message=str(e)))


def run_textual(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="scrape", add_help=False)
    parser.add_argument("url", nargs="?", default=None)
    parser.add_argument("-o", "--output", type=Path, default=Path("downloads"))
    parser.add_argument("--mode", choices=["auto", "video", "images"], default="auto")
    parser.add_argument("--max-images", type=int, default=None)
    parser.add_argument("--frames-dir", type=Path, default=Path("assets/lain_frames"))
    parser.add_argument("--avatar-fps", type=float, default=10.0, help="Cap avatar FPS (GIFs are clamped to this).")
    parser.add_argument("--avatar-width", type=int, default=32, help="Avatar width in terminal characters.")
    parser.add_argument("--avatar-height", type=int, default=16, help="Avatar height in terminal characters.")
    parser.add_argument(
        "--avatar-backend",
        choices=["auto", "rich_pixels", "braille", "halfblock"],
        default="halfblock",
    )
    parser.add_argument("--theme", type=str, default=None, help="Override saved Textual theme.")
    args, _unknown = parser.parse_known_args(argv)

    frames_dir = ensure_frames_dir(args.frames_dir)
    settings = load_ui_settings()
    theme = args.theme if isinstance(args.theme, str) and args.theme.strip() else settings.theme
    app = ScrapeTextualApp(
        ScrapeTextualArgs(
            url=args.url,
            output=args.output,
            mode=args.mode,
            max_images=args.max_images,
            frames_dir=frames_dir,
            avatar_fps=args.avatar_fps,
            avatar_backend=args.avatar_backend,  # type: ignore[arg-type]
            avatar_width_chars=int(args.avatar_width),
            avatar_height_chars=int(args.avatar_height),
            theme=theme,
        )
    )
    result = app.run()
    return int(result) if isinstance(result, int) else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(run_textual(sys.argv[1:]))
