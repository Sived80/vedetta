"""Data paths and environment parameters: a single source of truth.

In the LXC container the data lives in config/ (default, as always); as an add-on
of Home Assistant you set VEDETTA_DATA_DIR=/data. No dependency on other
app modules (applog imports it too)."""
import os
from pathlib import Path

_DEFAULT = Path(__file__).resolve().parent.parent / "config"
DATA_DIR = Path(os.environ.get("VEDETTA_DATA_DIR") or _DEFAULT)

try:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
except OSError:
    pass  # folder not writable: errors will surface at the first write


def data_path(name: str) -> Path:
    return DATA_DIR / name


# Prefix of generated URLs (HA ingress): empty = app served at the root.
def env_base_path() -> str:
    return normalize_base(os.environ.get("VEDETTA_BASE_PATH", ""))


def normalize_base(value: str | None) -> str:
    """'/abc/' -> '/abc'; empty or '/' -> ''. Only URL-safe characters."""
    value = (value or "").strip().rstrip("/")
    if not value or not value.startswith("/"):
        return ""
    if not all(c.isalnum() or c in "/-_.~" for c in value):
        return ""
    return value
