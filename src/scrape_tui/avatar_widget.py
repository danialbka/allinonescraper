from __future__ import annotations

from pathlib import Path
from time import perf_counter

from rich.text import Text
from textual.reactive import reactive
from textual.widget import Widget

from .avatar_renderer import AvatarBackend, AvatarRenderer


class AvatarWidget(Widget):
    DEFAULT_CSS = """
    AvatarWidget {
        width: 34;
        height: 18;
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

        self._frames = []
        self._frame_index = 0
        self._load_seconds: float | None = None

    @property
    def frames_loaded(self) -> int:
        return len(self._frames)

    @property
    def load_seconds(self) -> float | None:
        return self._load_seconds

    def on_mount(self) -> None:
        started = perf_counter()
        self._frames = AvatarRenderer(
            frames_dir=self.frames_dir,
            width_chars=self.width_chars,
            height_chars=self.height_chars,
            backend=self.backend,
        ).load_and_render()
        self._load_seconds = perf_counter() - started

        if self._frames and self.fps > 0:
            self.set_interval(1.0 / self.fps, self._advance_frame)
        self.refresh()

    def _advance_frame(self) -> None:
        if not self._frames:
            return
        self._frame_index = (self._frame_index + 1) % len(self._frames)
        self.refresh()

    def render(self):
        if not self._frames:
            if not self.frames_dir.exists():
                msg = f"Missing frames:\n{self.frames_dir}"
            else:
                msg = f"No PNG frames in:\n{self.frames_dir}"
            return Text(msg, style="dim")
        return self._frames[self._frame_index]

