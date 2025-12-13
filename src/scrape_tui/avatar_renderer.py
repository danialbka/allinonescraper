from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Literal

from PIL import Image
from PIL import ImageSequence
from rich.color import Color
from rich.console import RenderableType
from rich.style import Style
from rich.text import Text

AvatarBackend = Literal["auto", "rich_pixels", "braille", "halfblock"]


@dataclass(frozen=True)
class RenderedFrame:
    renderable: RenderableType
    duration_s: float


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


@dataclass(frozen=True)
class BrailleOptions:
    width_chars: int = 64
    height_chars: int = 32
    background_rgb: tuple[int, int, int] = (0, 0, 0)
    resample: int = int(getattr(Image, "Resampling", Image).LANCZOS)


class BrailleRenderer:
    """Render images using 2x4 braille cells with truecolor fg/bg."""

    def __init__(self, options: BrailleOptions) -> None:
        self.options = options

    @staticmethod
    def _braille_char(mask: int) -> str:
        return chr(0x2800 + (mask & 0xFF))

    @staticmethod
    def _dot_bit(dx: int, dy: int) -> int:
        # Braille dots (Unicode):
        # (0,0)=1 (0,1)=2 (0,2)=3 (1,0)=4 (1,1)=5 (1,2)=6 (0,3)=7 (1,3)=8
        if dx == 0 and dy == 0:
            return 0x01
        if dx == 0 and dy == 1:
            return 0x02
        if dx == 0 and dy == 2:
            return 0x04
        if dx == 1 and dy == 0:
            return 0x08
        if dx == 1 and dy == 1:
            return 0x10
        if dx == 1 and dy == 2:
            return 0x20
        if dx == 0 and dy == 3:
            return 0x40
        if dx == 1 and dy == 3:
            return 0x80
        return 0

    @staticmethod
    def _luma(rgb: tuple[int, int, int]) -> float:
        r, g, b = rgb
        return 0.2126 * r + 0.7152 * g + 0.0722 * b

    @staticmethod
    def _kmeans2(colors: list[tuple[int, int, int]]) -> tuple[tuple[int, int, int], tuple[int, int, int], list[int]]:
        # Tiny 2-means for 8 points: init by min/max luma, iterate a few times.
        if not colors:
            return (0, 0, 0), (0, 0, 0), []

        min_c = min(colors, key=BrailleRenderer._luma)
        max_c = max(colors, key=BrailleRenderer._luma)
        c0 = (float(min_c[0]), float(min_c[1]), float(min_c[2]))
        c1 = (float(max_c[0]), float(max_c[1]), float(max_c[2]))
        assignments = [0] * len(colors)

        for _ in range(4):
            sum0 = [0.0, 0.0, 0.0]
            sum1 = [0.0, 0.0, 0.0]
            n0 = 0
            n1 = 0
            for i, (r, g, b) in enumerate(colors):
                d0 = (r - c0[0]) ** 2 + (g - c0[1]) ** 2 + (b - c0[2]) ** 2
                d1 = (r - c1[0]) ** 2 + (g - c1[1]) ** 2 + (b - c1[2]) ** 2
                if d1 < d0:
                    assignments[i] = 1
                    sum1[0] += r
                    sum1[1] += g
                    sum1[2] += b
                    n1 += 1
                else:
                    assignments[i] = 0
                    sum0[0] += r
                    sum0[1] += g
                    sum0[2] += b
                    n0 += 1

            if n0 > 0:
                c0 = (sum0[0] / n0, sum0[1] / n0, sum0[2] / n0)
            if n1 > 0:
                c1 = (sum1[0] / n1, sum1[1] / n1, sum1[2] / n1)

        center0 = (int(round(c0[0])), int(round(c0[1])), int(round(c0[2])))
        center1 = (int(round(c1[0])), int(round(c1[1])), int(round(c1[2])))
        return center0, center1, assignments

    def render(self, image: Image.Image) -> Text:
        opts = self.options
        target_px = (opts.width_chars * 2, opts.height_chars * 4)

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

        def cached_style(fg: tuple[int, int, int], bg: tuple[int, int, int]) -> Style:
            key = (fg, bg)
            existing = style_cache.get(key)
            if existing is not None:
                return existing
            created = Style(color=cached_color(fg), bgcolor=cached_color(bg))
            style_cache[key] = created
            return created

        out = Text(no_wrap=True, end="")
        for cy in range(opts.height_chars):
            current_style_key: tuple[tuple[int, int, int], tuple[int, int, int]] | None = None
            current_char: str | None = None
            run: list[str] = []

            for cx in range(opts.width_chars):
                samples: list[tuple[int, int, int]] = []
                bits = []
                for dy in range(4):
                    for dx in range(2):
                        x = cx * 2 + dx
                        y = cy * 4 + dy
                        r, g, b, _a = px[x, y]
                        samples.append((r, g, b))
                        bits.append(self._dot_bit(dx, dy))

                c0, c1, assigns = self._kmeans2(samples)
                # Put the brighter cluster in the foreground (dots).
                if self._luma(c0) >= self._luma(c1):
                    fg, bg = c0, c1
                    fg_cluster = 0
                else:
                    fg, bg = c1, c0
                    fg_cluster = 1

                mask = 0
                for idx, a in enumerate(assigns):
                    if a == fg_cluster:
                        mask |= bits[idx]

                ch = self._braille_char(mask)
                style_key = (fg, bg)

                if current_style_key is None:
                    current_style_key = style_key
                    current_char = ch
                    run.append(ch)
                    continue

                if style_key == current_style_key and ch == current_char:
                    run.append(ch)
                    continue

                out.append("".join(run), cached_style(*current_style_key))
                run = [ch]
                current_style_key = style_key
                current_char = ch

            if current_style_key is not None and run:
                out.append("".join(run), cached_style(*current_style_key))

            if cy != opts.height_chars - 1:
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
        default_fps: float = 10.0,
    ) -> None:
        self.frames_dir = frames_dir
        self.width_chars = width_chars
        self.height_chars = height_chars
        self.backend = backend
        self.default_fps = default_fps

    def load_and_render(self) -> list[RenderedFrame]:
        if self.frames_dir.is_file() and self.frames_dir.suffix.lower() == ".gif":
            return self._load_and_render_gif(self.frames_dir)

        paths = iter_frame_paths(self.frames_dir)
        if not paths:
            return []

        images = [Image.open(p) for p in paths]
        try:
            renderables = self._render_images(images)
        finally:
            for im in images:
                try:
                    im.close()
                except Exception:
                    pass

        duration_s = 1.0 / max(1e-6, float(self.default_fps))
        return [RenderedFrame(renderable=r, duration_s=duration_s) for r in renderables]

    def _render_images(self, images: Iterable[Image.Image]) -> list[RenderableType]:
        if self.backend in {"auto", "rich_pixels"}:
            rendered = self._try_rich_pixels(images)
            if rendered is not None:
                return rendered
            if self.backend == "rich_pixels":
                raise RuntimeError(
                    "Backend 'rich_pixels' was requested but rich_pixels could not be used. "
                    "Install it (`pip install rich-pixels`) or use backend='braille'/'halfblock'."
                )

        if self.backend in {"auto", "braille"}:
            rendered = self._render_braille(images)
            if self.backend == "braille":
                return rendered
            if rendered:
                return rendered

        return self._render_halfblock(images)

    def _render_braille(self, images: Iterable[Image.Image]) -> list[RenderableType]:
        renderer = BrailleRenderer(
            BrailleOptions(width_chars=self.width_chars, height_chars=self.height_chars)
        )
        return [renderer.render(im) for im in images]

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

    def _load_and_render_gif(self, gif_path: Path) -> list[RenderedFrame]:
        with Image.open(gif_path) as im:
            frames: list[Image.Image] = []
            durations: list[float] = []

            base = Image.new("RGBA", im.size, (0, 0, 0, 0))
            previous = base.copy()

            for frame in ImageSequence.Iterator(im):
                duration_ms = frame.info.get("duration") or im.info.get("duration") or 100
                try:
                    duration_s = max(0.02, float(duration_ms) / 1000.0)
                except Exception:
                    duration_s = 0.1

                try:
                    disposal = int(getattr(frame, "disposal_method", 0) or frame.info.get("disposal") or 0)
                except Exception:
                    disposal = 0

                previous = base.copy()
                rgba = frame.convert("RGBA")
                composed = Image.alpha_composite(base, rgba)

                frames.append(composed)
                durations.append(duration_s)

                if disposal == 2:
                    base = Image.new("RGBA", im.size, (0, 0, 0, 0))
                elif disposal == 3:
                    base = previous
                else:
                    base = composed

            renderables = self._render_images(frames)
            return [RenderedFrame(renderable=r, duration_s=durations[i]) for i, r in enumerate(renderables)]
