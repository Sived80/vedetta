"""The files Home Assistant reads to show the app (config.yaml, repository.yaml) must be valid YAML
and have the required fields: an error here makes the app invisible in the store with no message at all."""
import re
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

# Home Assistant downloads the signed images built by GitHub (.github/workflows/images.yml): the name in config.yaml is the one
# the workflow pushes, and the workflow builds every architecture config.yaml promises (a missing one would fail to install)
images = load(ROOT / ".github" / "workflows" / "images.yml")
assert cfg.get("image") == "ghcr.io/sived80/{arch}-vedetta", "config.yaml: image"
assert "ghcr.io/sived80/${{ matrix.arch }}-vedetta" in (ROOT / ".github" / "workflows" / "images.yml").read_text(encoding="utf-8")
built = {m["arch"] for m in images["jobs"]["image"]["strategy"]["matrix"]["include"]}
assert set(cfg["arch"]) <= built, ("architectures without an image", set(cfg["arch"]) - built)

# every action of the workflows is named by its commit, not by a tag that can be moved
for wf in sorted((ROOT / ".github" / "workflows").glob("*.yml")):
    for n, ln in enumerate(wf.read_text(encoding="utf-8").splitlines(), 1):
        m = re.search(r"uses:\s*([^\s#]+)", ln)
        if m and not m.group(1).startswith("./"):
            assert re.search(r"@[0-9a-f]{40}$", m.group(1)), f"{wf.name}:{n} action not pinned by its commit: {m.group(1)}"
print("TUTTO OK")
