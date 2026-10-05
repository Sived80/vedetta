"""The files Home Assistant reads to show the app (config.yaml, repository.yaml) must be valid YAML
and have the required fields: an error here makes the app invisible in the store with no message at all."""
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

# the Dockerfile image must have a base reference and the startup file must exist
assert (APP / "Dockerfile").exists() and (APP / "run.sh").exists()
print("TUTTO OK")
