"""Settings: one `.env` file (the share link, the describer's key and model)
plus where the index lives. Nothing here talks to the network."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


@dataclass
class Settings:
    share_link: str
    root_id: str
    data_dir: Path
    model_key: str = ""
    model: str = "MiniMax-M3.1-Flash-Preview"
    base_url: str = "https://api.minimax.io/v1"
    effort: str = "medium"  # reasoning_effort; MiniMax M3.x defaults to "max" when unset
    google_api_key: str = ""
    env_path: Path | None = None

    @property
    def db_path(self) -> Path:
        return self.data_dir / self.root_id / "index.db"


def folder_id(link: str) -> str:
    """The folder id in a Drive share link (or a bare id)."""
    m = re.search(r"/folders/([\w-]{10,})", link) or re.search(r"[?&]id=([\w-]{10,})", link)
    if m:
        return m.group(1)
    if re.fullmatch(r"[\w-]{10,}", link.strip()):
        return link.strip()
    raise ValueError(f"not a Google Drive folder link: {link!r}")


def read_env(path: Path) -> dict[str, str]:
    """KEY=value lines; `#` starts a comment (whole line, or after a space)."""
    out: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        v = re.split(r"\s+#", v, maxsplit=1)[0].strip().strip('"').strip("'")
        out[k.strip()] = v
    return out


def find_env(explicit: str | None = None) -> Path | None:
    if explicit:
        return Path(explicit).expanduser()
    if os.environ.get("DRIVE_LENS_ENV"):
        return Path(os.environ["DRIVE_LENS_ENV"]).expanduser()
    for d in [Path.cwd(), *Path.cwd().parents]:
        if (d / ".env").is_file() and "DRIVE_LENS_SHARE_LINK" in (d / ".env").read_text(encoding="utf-8", errors="replace"):
            return d / ".env"
    return REPO_ROOT / ".env" if (REPO_ROOT / ".env").is_file() else None


def load(env_file: str | None = None, share_link: str | None = None) -> Settings:
    """Settings from the .env file, overridden by real environment variables."""
    path = find_env(env_file)
    env = read_env(path) if path and path.is_file() else {}
    env.update({k: v for k, v in os.environ.items() if k.startswith(("DRIVE_LENS_", "MINIMAX_", "GOOGLE_API_KEY"))})
    link = share_link or env.get("DRIVE_LENS_SHARE_LINK", "")
    if not link:
        raise SystemExit("No Drive folder: set DRIVE_LENS_SHARE_LINK in .env (see .env.example)")
    # Embedder settings are read by embed.py from the environment; let .env set them.
    for k in ("DRIVE_LENS_DTYPE", "DRIVE_LENS_DEVICE", "DRIVE_LENS_MIN_SIM", "DRIVE_LENS_EMBED_MODEL"):
        if env.get(k):
            os.environ.setdefault(k, env[k])
    base = path.parent if path else Path.cwd()
    data = Path(env.get("DRIVE_LENS_DATA") or base / "data").expanduser()
    return Settings(
        share_link=link,
        root_id=folder_id(link),
        data_dir=data,
        model_key=env.get("MINIMAX_API_KEY", ""),
        model=env.get("MINIMAX_MODEL") or Settings.model,
        base_url=env.get("MINIMAX_BASE_URL") or Settings.base_url,
        effort=env.get("MINIMAX_REASONING_EFFORT") or Settings.effort,
        google_api_key=env.get("GOOGLE_API_KEY", ""),
        env_path=path,
    )
