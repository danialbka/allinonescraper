from __future__ import annotations

from pathlib import Path
from time import perf_counter

from rich.text import Text
from textual.reactive import reactive
from textual.widget import Widget

from .avatar_renderer import AvatarBackend, AvatarRenderer, RenderedFrame


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
        frames_dir: Path,
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
        if duration <= 0:
            duration = 1.0 / max(1e-6, float(self.fps))
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
                msg = f"Missing avatar:\n{self.frames_dir}"
            else:
                msg = f"No PNG frames / GIF at:\n{self.frames_dir}"
            return Text(msg, style="dim")
        return self._frames[self._frame_index].renderable
