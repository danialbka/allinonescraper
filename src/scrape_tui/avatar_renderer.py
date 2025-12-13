from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Literal

from PIL import Image
from rich.color import Color
from rich.console import RenderableType
from rich.style import Style
from rich.text import Text

AvatarBackend = Literal["auto", "rich_pixels", "halfblock"]


def iter_frame_paths(frames_dir: Path) -> list[Path]:
    if not frames_dir.exists():
        return []
    if not frames_dir.is_dir():
        return []

    paths = [p for p in frames_dir.iterdir() if p.is_file() and p.suffix.lower() == ".png"]
    paths.sort(key=lambda p: p.name)
    return paths


def _composite_rgba_on_bg(image: Image.Image, *, bg_rgb: tuple[int, int, int]) -> Image.Image:
    rgba = image.convert("RGBA")
    background = Image.new("RGBA", rgba.size, (*bg_rgb, 255))
    return Image.alpha_composite(background, rgba)


@dataclass(frozen=True)
class HalfBlockOptions:
    width_chars: int = 32
    height_chars: int = 16
    background_rgb: tuple[int, int, int] = (0, 0, 0)
    resample: int = int(getattr(Image, "Resampling", Image).LANCZOS)


class HalfBlockRenderer:
    """Render images using Unicode half blocks (▀) with truecolor fg/bg."""

    def __init__(self, options: HalfBlockOptions) -> None:
        self.options = options

    def render(self, image: Image.Image) -> Text:
        opts = self.options
        target_px = (opts.width_chars, opts.height_chars * 2)

        rgba = _composite_rgba_on_bg(image, bg_rgb=opts.background_rgb)
        rgba = rgba.resize(target_px, resample=opts.resample)
        px = rgba.load()
        if px is None:
            return Text("")

        color_cache: dict[tuple[int, int, int], Color] = {}
        style_cache: dict[tuple[tuple[int, int, int], tuple[int, int, int]], Style] = {}

        def cached_color(rgb: tuple[int, int, int]) -> Color:
            existing = color_cache.get(rgb)
            if existing is not None:
                return existing
            created = Color.from_rgb(*rgb)
            color_cache[rgb] = created
            return created

        def cached_style(top: tuple[int, int, int], bottom: tuple[int, int, int]) -> Style:
            key = (top, bottom)
            existing = style_cache.get(key)
            if existing is not None:
                return existing
            created = Style(color=cached_color(top), bgcolor=cached_color(bottom))
            style_cache[key] = created
            return created

        out = Text(no_wrap=True, end="")
        for row in range(opts.height_chars):
            current_key: tuple[tuple[int, int, int], tuple[int, int, int]] | None = None
            run: list[str] = []

            for col in range(opts.width_chars):
                r1, g1, b1, _a1 = px[col, row * 2]
                r2, g2, b2, _a2 = px[col, row * 2 + 1]
                key = ((r1, g1, b1), (r2, g2, b2))

                if current_key is None:
                    current_key = key
                    run.append("▀")
                    continue

                if key == current_key:
                    run.append("▀")
                    continue

                out.append("".join(run), cached_style(*current_key))
                run = ["▀"]
                current_key = key

            if current_key is not None and run:
                out.append("".join(run), cached_style(*current_key))

            if row != opts.height_chars - 1:
                out.append("\n")

        return out


class AvatarRenderer:
    def __init__(
        self,
        *,
        frames_dir: Path,
        width_chars: int = 32,
        height_chars: int = 16,
        backend: AvatarBackend = "auto",
    ) -> None:
        self.frames_dir = frames_dir
        self.width_chars = width_chars
        self.height_chars = height_chars
        self.backend = backend

    def load_and_render(self) -> list[RenderableType]:
        paths = iter_frame_paths(self.frames_dir)
        if not paths:
            return []

        images = [Image.open(p) for p in paths]
        try:
            return self._render_images(images)
        finally:
            for im in images:
                try:
                    im.close()
                except Exception:
                    pass

    def _render_images(self, images: Iterable[Image.Image]) -> list[RenderableType]:
        if self.backend in {"auto", "rich_pixels"}:
            rendered = self._try_rich_pixels(images)
            if rendered is not None:
                return rendered
            if self.backend == "rich_pixels":
                raise RuntimeError(
                    "Backend 'rich_pixels' was requested but rich_pixels could not be used. "
                    "Install it (`pip install rich-pixels`) or use backend='halfblock'."
                )

        return self._render_halfblock(images)

    def _render_halfblock(self, images: Iterable[Image.Image]) -> list[RenderableType]:
        renderer = HalfBlockRenderer(
            HalfBlockOptions(width_chars=self.width_chars, height_chars=self.height_chars)
        )
        return [renderer.render(im) for im in images]

    def _try_rich_pixels(self, images: Iterable[Image.Image]) -> list[RenderableType] | None:
        try:
            from rich_pixels import Pixels  # type: ignore
        except Exception:
            return None

        rendered: list[RenderableType] = []
        for im in images:
            try:
                pixels = Pixels.from_image(im, resize=(self.width_chars, self.height_chars))
            except TypeError:
                try:
                    pixels = Pixels.from_image(im, width=self.width_chars, height=self.height_chars)
                except Exception:
                    return None
            except Exception:
                return None
            rendered.append(pixels)
        return rendered

