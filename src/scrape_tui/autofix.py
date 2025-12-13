from __future__ import annotations

import json
import subprocess
from pathlib import Path
from shutil import which

from rich.console import Console
from rich.prompt import Confirm


def find_project_root(start: Path | None = None) -> Path | None:
    current = (start or Path.cwd()).resolve()
    for parent in [current, *current.parents]:
        if not (parent / "src" / "scrape_tui").exists():
            continue
        if not any((parent / marker).exists() for marker in ("pyproject.toml", "setup.cfg", "setup.py")):
            continue
        return parent
    return None


def _task_id_from_codex_json(stdout: str) -> str | None:
    def find(obj) -> str | None:
        if isinstance(obj, dict):
            for key in ("task_id", "taskId"):
                value = obj.get(key)
                if isinstance(value, str) and value.strip():
                    return value.strip()
            task = obj.get("task")
            if isinstance(task, dict):
                for key in ("task_id", "taskId", "id"):
                    value = task.get(key)
                    if isinstance(value, str) and value.strip():
                        return value.strip()
            for value in obj.values():
                found = find(value)
                if found:
                    return found
        elif isinstance(obj, list):
            for item in obj:
                found = find(item)
                if found:
                    return found
        return None

    task_id: str | None = None
    for line in stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        found = find(obj)
        if found:
            task_id = found
    return task_id


def offer_codex_autofix(console: Console, *, url: str, error: str) -> bool:
    codex = which("codex")
    if not codex:
        console.print("[yellow]Codex CLI not found on PATH.[/yellow]")
        return False

    root = find_project_root()
    if not root:
        console.print("[yellow]Auto-fix requires running from the scrape-tui source directory.[/yellow]")
        return False

    console.print(f"[bold]Codex auto-fix (developer mode)[/bold]\nRepo: {root}")
    if not Confirm.ask("Run Codex to try to fix this issue?", default=False):
        return False

    status = subprocess.run(
        [codex, "login", "status"],
        cwd=root,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    if status.returncode != 0:
        console.print("[yellow]Codex is not logged in. Starting device auth...[/yellow]")
        subprocess.run([codex, "login", "--device-auth"], cwd=root, check=False)

    prompt = (
        "scrape-tui failed to download a URL.\n\n"
        f"URL: {url}\n"
        f"Error: {error}\n\n"
        "Please update the code to either support this URL/site or improve robustness and error "
        "handling. Prefer small, safe changes. If support isn't feasible, improve the user-facing "
        "message and add a fallback path.\n"
    )

    result = subprocess.run(
        [codex, "exec", "--json", "--skip-git-repo-check", "-C", str(root), prompt],
        cwd=root,
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        console.print("[red]Codex exec failed.[/red]")
        if result.stderr.strip():
            console.print(result.stderr.strip())
        return False

    task_id = _task_id_from_codex_json(result.stdout)
    if not task_id:
        console.print("[yellow]Could not determine Codex task id from output.[/yellow]")
        console.print("Re-run manually: `codex exec -C . <prompt>` and then `codex apply <TASK_ID>`")
        return False

    if not Confirm.ask(f"Apply Codex patch {task_id} to this repo?", default=False):
        console.print(f"To apply later: `codex apply {task_id}` (run inside {root})")
        return False

    applied = subprocess.run([codex, "apply", task_id], cwd=root, check=False)
    if applied.returncode != 0:
        console.print("[red]Failed to apply the Codex patch.[/red]")
        return False

    console.print("[green]Patch applied. Re-run `scrape` to try again.[/green]")
    return True
