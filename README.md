# allinonescraper

All‑in‑one downloader TUI for videos + images. Paste a URL, pick a quality (for videos), and it saves the result to disk.

![allinonescraper screenshot](Screenshot_72.png)

## What it can download

- Videos (via `yt-dlp`) with a quality/resolution picker
- Direct image URLs (e.g. `.jpg`, `.png`, `.webp`, etc.)
- Images from a web page (scrapes `<img>` + common lazy-loading attributes + `srcset`)

## Install

### Windows (no Python required)

Download the latest release from:

https://github.com/danialbka/allinonescraper/releases/latest

Either:
- Download `allinonescraper.exe` and run it, or
- Download `allinonescraper-windows-x64.zip`, unzip it, then run `allinonescraper.exe`.

Notes:
- The EXE bundles Python + dependencies (no install needed).
- Double-clicking `allinonescraper.exe` opens a terminal window and runs the TUI.
- For best-quality video (video+audio merges), install `ffmpeg` and make sure it’s on `PATH`.

### From source (Linux/macOS/Windows)

```bash
python3 -m pip install -e .
```

Notes:
- For high-res video downloads/merges, install `ffmpeg` and ensure it is on `PATH`.

## Use

Run the app and paste a URL:

```bash
allinonescraper
```

### Textual UI (animated avatar)

When you start `scrape` / `allinonescraper` interactively (no URL argument), it launches a Textual UI with an animated avatar panel (Unicode + ANSI truecolor; no Kitty/SIXEL).

- Add frames to `./assets/lain_frames/` named `000.png`, `001.png`, ...
- Or point `--frames-dir` at a `.gif` (or drop a `.gif` into `./assets/` and it will be auto-picked).
- If you don't add frames, it auto-generates a small placeholder animation into `~/.cache/scrape_tui/avatar_frames/`.
- Force the old prompt-based UI: `scrape --ui classic`
 - For max quality (heavier): `--avatar-backend braille --avatar-width 64 --avatar-height 32`

It will return to the main menu after each download; submit a blank URL to exit.

When running in the default `auto` mode, it will also ask whether you want to download the URL as a video or as images.

You can also run:

```bash
scrape
```

Or without installing:

```bash
PYTHONPATH=src python3 -m scrape_tui
```

### Examples

```bash
allinonescraper https://www.youtube.com/watch?v=...
allinonescraper --mode images --max-images 50 https://example.com/article
allinonescraper --output ./downloads https://example.com/picture.jpg
```

### Options

- `--mode auto|video|images` (default: `auto`)
- `--max-images N` (when scraping a page)
- `--output PATH` (base directory; downloads go to `PATH/<domain>/<timestamp>/`)
- `--no-codex` (disable in-app Codex auto-fix prompts)

## How it works

In `--mode auto`:

1. Probe the URL with `yt-dlp` to see if it looks like a video.
2. If it is, show a quality list and download using the selected format selector.
3. Otherwise, fall back to images:
   - If the URL is an image (or the response `Content-Type` is `image/*`), download it directly.
   - If it’s HTML, parse the page and download discovered image URLs.

Downloads are organized under `./downloads/<domain>/<timestamp>/`.

## Codex auto-fix (developer mode)

If a site breaks, on errors it can offer an in-app Codex auto-fix. It will:

1. Ask permission to run Codex
2. If needed, prompt for headless login using `codex login --device-auth`
3. Run `codex exec` with the failing URL + error message
4. Ask permission to apply the generated patch via `codex apply`

This can modify your local source tree; review changes before pushing.

## Troubleshooting

- Update `yt-dlp`: `python3 -m pip install -U yt-dlp`
- Install `ffmpeg` for high-res formats (video+audio merging)
- Some sites require cookies/login; `yt-dlp` supports `--cookies-from-browser` (not wired into the TUI yet).
