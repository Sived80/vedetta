"""I file che Home Assistant legge per mostrare l'app (config.yaml, repository.yaml) devono essere YAML validi
e avere i campi obbligatori: un errore qui rende l'app invisibile nel negozio senza nessun messaggio."""
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
APP = ROOT / "vedetta"


def load(path: Path) -> dict:
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        print("YAML NON VALIDO:", path, exc)
        sys.exit(1)
    assert isinstance(data, dict), path
    return data


cfg = load(APP / "config.yaml")
for key in ("name", "version", "slug", "description", "arch", "startup", "ingress", "ingress_port", "homeassistant_api"):
    assert key in cfg, f"config.yaml: manca {key}"
assert isinstance(cfg["version"], str), "config.yaml: version va tra virgolette"
assert isinstance(cfg["arch"], list) and cfg["arch"], "config.yaml: arch"
assert cfg["slug"] == "vedetta"
assert (APP / "VERSION").read_text(encoding="utf-8").strip() == cfg["version"], "VERSION diversa da config.yaml"
assert "example.invalid" not in (APP / "config.yaml").read_text(encoding="utf-8"), "config.yaml: URL segnaposto"

repo = load(ROOT / "repository.yaml")
for key in ("name", "url", "maintainer"):
    assert repo.get(key), f"repository.yaml: manca {key}"
assert repo["url"].startswith("https://github.com/") and "example.invalid" not in repo["url"], repo["url"]

# l'immagine del Dockerfile deve avere un riferimento di base e il file di avvio deve esistere
assert (APP / "Dockerfile").exists() and (APP / "run.sh").exists()
print("TUTTO OK")
