# Animated avatar panel (Textual + Rich, Option C)

This is a minimal Textual app that renders an animated PNG avatar in a fixed-size panel using Unicode half-block characters (no Kitty graphics protocol, no SIXEL). It works in Windows Terminal with ANSI truecolor (including WSL).

## Add frames

1. Put PNG frames in `./assets/lain_frames/`
2. Name them `000.png`, `001.png`, `002.png`, ...

Or use a GIF:

```bash
scrape --ui textual --frames-dir ./assets/your_avatar.gif
```

The Textual UI defaults to a fast mode: `halfblock` rendering at `32×16` terminal characters.

If you don’t have frames yet, the app auto-generates a small placeholder animation into `~/.cache/scrape_tui/avatar_frames/` and uses that automatically.

You can tune quality/performance:

```bash
scrape --ui textual --avatar-backend halfblock --avatar-width 32 --avatar-height 16
scrape --ui textual --avatar-backend braille --avatar-width 64 --avatar-height 32
```

## Install (WSL)

```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -r requirements.txt
```

Optional (if you want the `rich_pixels` backend when available):

```bash
python3 -m pip install rich-pixels
```

## Run

```bash
python3 app.py
```

With options:

```bash
python3 app.py --frames-dir ./assets/lain_frames --fps 12 --backend halfblock
```

Controls: `q` to quit.

## How rendering works

- The default backend is a custom half-block renderer in `src/scrape_tui/avatar_renderer.py`.
- Each terminal cell uses `▀` with:
  - foreground color = the “top” pixel
  - background color = the “bottom” pixel
- Frames are preloaded and pre-rendered once at startup, then the widget swaps cached renderables at the configured FPS.
