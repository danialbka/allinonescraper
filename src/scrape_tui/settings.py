from __future__ import annotations

from dataclasses import asdict, dataclass
import json
import os
from pathlib import Path


def _xdg_config_dir() -> Path:
    raw = os.environ.get("XDG_CONFIG_HOME")
    if raw:
        return Path(raw).expanduser()
    return Path.home() / ".config"


def settings_path() -> Path:
    return _xdg_config_dir() / "scrape_tui" / "settings.json"


@dataclass
class UiSettings:
    theme: str | None = None


def load_ui_settings() -> UiSettings:
    path = settings_path()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return UiSettings()
    except Exception:
        return UiSettings()

    if not isinstance(data, dict):
        return UiSettings()
    theme = data.get("theme")
    return UiSettings(theme=theme if isinstance(theme, str) and theme.strip() else None)


def save_ui_settings(settings: UiSettings) -> None:
    path = settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = asdict(settings)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")

