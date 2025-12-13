from __future__ import annotations

from math import cos, pi, sin
import os
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

from .avatar_renderer import iter_frame_paths


def _xdg_cache_dir() -> Path:
    raw = os.environ.get("XDG_CACHE_HOME")
    if raw:
        return Path(raw).expanduser()
    return Path.home() / ".cache"


def generated_frames_dir() -> Path:
    return _xdg_cache_dir() / "scrape_tui" / "avatar_frames"


def ensure_frames_dir(frames_dir: Path, *, frame_count: int = 48) -> Path:
    """Return a directory containing frames; generates placeholders if empty/missing.

    If `frames_dir` has PNGs, it's returned as-is. Otherwise, we generate a small
    offline animation into a cache directory and return that path.
    """

    existing = iter_frame_paths(frames_dir)
    if existing:
        return frames_dir

    cache_dir = generated_frames_dir()
    if len(iter_frame_paths(cache_dir)) >= 2:
        return cache_dir

    cache_dir.mkdir(parents=True, exist_ok=True)
    _generate_placeholder_frames(cache_dir, frame_count=frame_count)
    return cache_dir


def _generate_placeholder_frames(
    out_dir: Path,
    *,
    frame_count: int,
    size_px: tuple[int, int] = (128, 128),
) -> None:
    w, h = size_px
    for i in range(frame_count):
        t = i / max(1, frame_count)

        img = Image.new("RGBA", (w, h), (0, 0, 0, 255))
        draw = ImageDraw.Draw(img)

        base_r = 10 + int(10 * sin(2 * pi * t))
        base_g = 8 + int(8 * sin(2 * pi * (t + 0.2)))
        base_b = 14 + int(12 * sin(2 * pi * (t + 0.4)))
        for y in range(h):
            v = y / max(1, h - 1)
            wave = 0.5 + 0.5 * sin(2 * pi * (t + v * 0.9))
            r = min(255, int(base_r + 30 * wave))
            g = min(255, int(base_g + 18 * wave))
            b = min(255, int(base_b + 40 * wave))
            if y % 4 == 0:
                r = int(r * 0.75)
                g = int(g * 0.75)
                b = int(b * 0.75)
            draw.line((0, y, w, y), fill=(r, g, b, 255))

        cx = w * (0.5 + 0.08 * sin(2 * pi * t))
        cy = h * (0.5 + 0.08 * cos(2 * pi * t))
        radius = min(w, h) * (0.23 + 0.03 * sin(2 * pi * (t + 0.1)))

        for k in range(10, 0, -1):
            kf = k / 10.0
            glow = int(110 * (1.0 - kf))
            alpha = int(22 * (1.0 - kf))
            rr = radius + k * 2
            draw.ellipse(
                (cx - rr, cy - rr, cx + rr, cy + rr),
                fill=(30 + glow, 40 + glow, 120 + glow, alpha),
            )

        draw.ellipse(
            (cx - radius, cy - radius, cx + radius, cy + radius),
            fill=(70, 90, 220, 210),
            outline=(200, 220, 255, 240),
            width=2,
        )

        highlight_angle = 2 * pi * t
        hx = cx + radius * 0.55 * cos(highlight_angle)
        hy = cy + radius * 0.55 * sin(highlight_angle)
        hr = radius * 0.25
        draw.ellipse((hx - hr, hy - hr, hx + hr, hy + hr), fill=(255, 255, 255, 90))

        glitch_y = int((t * 1.7 % 1.0) * h)
        draw.rectangle((0, glitch_y, w, min(h, glitch_y + 2)), fill=(255, 80, 220, 35))
        draw.rectangle((0, (glitch_y + 36) % h, w, min(h, ((glitch_y + 36) % h) + 1)), fill=(80, 255, 220, 20))

        img = img.filter(ImageFilter.GaussianBlur(radius=0.6))
        out_path = out_dir / f"{i:03d}.png"
        img.save(out_path)

