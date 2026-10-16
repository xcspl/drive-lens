"""Settings: one `.env` file (the share link, the describing model, the
embedding model, where the index lives), overridden by real environment
variables. Nothing here talks to the network. See .env.example."""

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
    llm_format: str = "openai"  # openai (chat completions) | anthropic (messages)
    llm_base_url: str = "https://api.minimax.io/v1"
    llm_api_key: str = ""
    llm_model: str = "MiniMax-M3.1-Flash-Preview"
    llm_effort: str = ""  # reasoning effort; empty = the provider's default
    google_api_key: str = ""
    db_file: Path | None = None  # DRIVE_LENS_DB; default <data>/<folder id>/index.db
    env_path: Path | None = None

    @property
    def db_path(self) -> Path:
        return self.db_file or self.data_dir / self.root_id / "index.db"


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
    env.update({k: v for k, v in os.environ.items() if k.startswith(("DRIVE_LENS_", "GOOGLE_API_KEY"))})
    link = share_link or env.get("DRIVE_LENS_SHARE_LINK", "")
    if not link:
        raise SystemExit("No Drive folder: set DRIVE_LENS_SHARE_LINK in .env (see .env.example)")
    # Embedder settings are read by embed.py from the environment; let .env set them.
    for k in ("DRIVE_LENS_EMBED_MODEL", "DRIVE_LENS_DTYPE", "DRIVE_LENS_DEVICE", "DRIVE_LENS_MIN_SIM"):
        if env.get(k):
            os.environ.setdefault(k, env[k])
    base = path.parent if path else Path.cwd()
    data = Path(env.get("DRIVE_LENS_DATA") or base / "data").expanduser()
    db = env.get("DRIVE_LENS_DB")
    fmt = (env.get("DRIVE_LENS_LLM_FORMAT") or Settings.llm_format).lower()
    if fmt not in ("openai", "anthropic"):
        raise SystemExit(f"DRIVE_LENS_LLM_FORMAT must be openai or anthropic, not {fmt!r}")
    return Settings(
        share_link=link,
        root_id=folder_id(link),
        data_dir=data,
        llm_format=fmt,
        llm_base_url=env.get("DRIVE_LENS_LLM_BASE_URL") or Settings.llm_base_url,
        llm_api_key=env.get("DRIVE_LENS_LLM_API_KEY", ""),
        llm_model=env.get("DRIVE_LENS_LLM_MODEL") or Settings.llm_model,
        llm_effort=env.get("DRIVE_LENS_LLM_EFFORT", ""),
        google_api_key=env.get("GOOGLE_API_KEY", ""),
        db_file=(Path(db).expanduser() if Path(db).expanduser().is_absolute() else base / db) if db else None,
        env_path=path,
    )
