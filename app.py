from __future__ import annotations

import sys
from pathlib import Path
from time import perf_counter

from rich.text import Text
from textual.app import App, ComposeResult
from textual.containers import Horizontal
from textual.reactive import reactive
from textual.widgets import Footer, Header, Static
from textual.widget import Widget

try:
    from scrape_tui.avatar_renderer import AvatarBackend, AvatarRenderer, RenderedFrame
    from scrape_tui.avatar_assets import ensure_frames_dir
except ModuleNotFoundError:
    sys.path.insert(0, str(Path(__file__).parent / "src"))
    from scrape_tui.avatar_renderer import AvatarBackend, AvatarRenderer, RenderedFrame
    from scrape_tui.avatar_assets import ensure_frames_dir


class AvatarWidget(Widget):
    DEFAULT_CSS = """
    AvatarWidget {
        border: round $primary;
        padding: 0;
    }
    """

    fps: reactive[float] = reactive(10.0)

    def __init__(
        self,
        *,
        frames_dir: Path = Path("./assets/lain_frames"),
        width_chars: int = 32,
        height_chars: int = 16,
        fps: float = 10.0,
        backend: AvatarBackend = "auto",
        id: str | None = None,
    ) -> None:
        super().__init__(id=id)
        self.frames_dir = frames_dir
        self.width_chars = width_chars
        self.height_chars = height_chars
        self.fps = fps
        self.backend = backend

        self._frames: list[RenderedFrame] = []
        self._frame_index = 0
        self._load_seconds: float | None = None
        self._timer = None

    @property
    def frames_loaded(self) -> int:
        return len(self._frames)

    @property
    def load_seconds(self) -> float | None:
        return self._load_seconds

    def on_mount(self) -> None:
        self.styles.width = self.width_chars + 2
        self.styles.height = self.height_chars + 2

        started = perf_counter()
        self._frames = AvatarRenderer(
            frames_dir=self.frames_dir,
            width_chars=self.width_chars,
            height_chars=self.height_chars,
            backend=self.backend,
            default_fps=self.fps,
        ).load_and_render()
        self._load_seconds = perf_counter() - started

        if self._frames:
            self._schedule_next()
        self.refresh()

    def _schedule_next(self) -> None:
        if not self._frames:
            return
        if self._timer is not None:
            try:
                self._timer.stop()
            except Exception:
                pass
        duration = float(self._frames[self._frame_index].duration_s)
        max_fps = float(self.fps)
        min_duration = (1.0 / max_fps) if max_fps > 0 else 0.0
        if duration <= 0:
            duration = min_duration if min_duration > 0 else 0.1
        elif min_duration > 0:
            duration = max(duration, min_duration)
        self._timer = self.set_timer(duration, self._advance_frame)

    def _advance_frame(self) -> None:
        if not self._frames:
            return
        self._frame_index = (self._frame_index + 1) % len(self._frames)
        self.refresh()
        self._schedule_next()

    def render(self):
        if not self._frames:
            if not self.frames_dir.exists():
                msg = f"Missing frames:\n{self.frames_dir}"
            else:
                msg = f"No PNG frames / GIF at:\n{self.frames_dir}"
            return Text(msg, style="dim")
        return self._frames[self._frame_index].renderable


class StatusWidget(Static):
    def set_text(self, text: str) -> None:
        self.update(Text(text))


class DemoApp(App):
    CSS = """
    #body {
        layout: horizontal;
        height: 1fr;
    }

    #status {
        width: 1fr;
        padding: 1 2;
    }

    #avatar_panel {
        margin: 1 2 0 0;
    }
    """

    BINDINGS = [
        ("q", "quit", "Quit"),
    ]

    def __init__(
        self,
        *,
        frames_dir: Path = Path("./assets/lain_frames"),
        fps: float = 10.0,
        backend: AvatarBackend = "halfblock",
        width_chars: int = 32,
        height_chars: int = 16,
    ) -> None:
        super().__init__()
        self.frames_dir = ensure_frames_dir(frames_dir)
        self.fps = fps
        self.backend = backend
        self.width_chars = width_chars
        self.height_chars = height_chars

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Horizontal(id="body"):
            yield StatusWidget(id="status")
            yield AvatarWidget(
                id="avatar_panel",
                frames_dir=self.frames_dir,
                width_chars=self.width_chars,
                height_chars=self.height_chars,
                fps=self.fps,
                backend=self.backend,
            )
        yield Footer()

    def on_mount(self) -> None:
        self._status = self.query_one("#status", StatusWidget)
        self._avatar = self.query_one("#avatar_panel", AvatarWidget)
        self.set_interval(0.5, self._update_status)
        self._update_status()

    def _update_status(self) -> None:
        load_s = self._avatar.load_seconds
        load_str = "loading…" if load_s is None else f"{load_s:.2f}s"
        self._status.set_text(
            "\n".join(
                [
                    "Placeholder status panel",
                    "",
                    f"Frames dir: {self.frames_dir}",
                    f"Backend: {self.backend}",
                    f"Target size: {self._avatar.width_chars}×{self._avatar.height_chars} chars",
                    f"FPS: {self.fps}",
                    f"Frames loaded: {self._avatar.frames_loaded} ({load_str})",
                    "",
                    "Controls:",
                    "  q  Quit",
                ]
            )
        )


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Textual demo: animated avatar panel (Option C rendering).")
    parser.add_argument(
        "--frames-dir",
        type=Path,
        default=Path("./assets/lain_frames"),
        help="Folder containing 000.png, 001.png, ...",
    )
    parser.add_argument("--fps", type=float, default=10.0, help="Cap avatar FPS (GIFs are clamped to this).")
    parser.add_argument(
        "--backend",
        choices=["auto", "rich_pixels", "braille", "halfblock"],
        default="halfblock",
        help="Rendering backend (auto prefers rich_pixels, then halfblock).",
    )
    parser.add_argument("--width", type=int, default=32, help="Avatar width in terminal characters.")
    parser.add_argument("--height", type=int, default=16, help="Avatar height in terminal characters.")
    args = parser.parse_args()

    DemoApp(
        frames_dir=args.frames_dir,
        fps=args.fps,
        backend=args.backend,
        width_chars=args.width,
        height_chars=args.height,
    ).run()
