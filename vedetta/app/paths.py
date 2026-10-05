"""Percorsi dei dati e parametri d'ambiente: un solo punto di verita'.

Nel container LXC i dati stanno in config/ (default, come sempre); come add-on
di Home Assistant si imposta VEDETTA_DATA_DIR=/data. Nessuna dipendenza da altri
moduli dell'app (lo importa anche applog)."""
import os
from pathlib import Path

_DEFAULT = Path(__file__).resolve().parent.parent / "config"
DATA_DIR = Path(os.environ.get("VEDETTA_DATA_DIR") or _DEFAULT)

try:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
except OSError:
    pass  # cartella non scrivibile: gli errori emergeranno alla prima scrittura


def data_path(name: str) -> Path:
    return DATA_DIR / name


# Prefisso degli URL generati (ingress di HA): vuoto = app servita alla radice.
def env_base_path() -> str:
    return normalize_base(os.environ.get("VEDETTA_BASE_PATH", ""))


def normalize_base(value: str | None) -> str:
    """'/abc/' -> '/abc'; vuoto o '/' -> ''. Solo caratteri sicuri per un URL."""
    value = (value or "").strip().rstrip("/")
    if not value or not value.startswith("/"):
        return ""
    if not all(c.isalnum() or c in "/-_.~" for c in value):
        return ""
    return value
