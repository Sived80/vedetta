"""run.sh calls no deprecated bashio function. bashio 0.18 renamed the bashio::addon.* / bashio::addons.* functions to
bashio::app.* / bashio::apps.* and keeps the old names only as aliases that log a deprecation warning at every start.
The base image named in the Dockerfile (ghcr.io/home-assistant/base 3.24-2026.11.0) ships bashio 0.19.0, which defines the new names."""
import re
import sys
from pathlib import Path

RUN_SH = Path(__file__).resolve().parent.parent / "vedetta" / "run.sh"
_DEPRECATED = re.compile(r"bashio::addons?\b")


def deprecated_calls(text: str) -> list[str]:
    return [ln.strip() for ln in text.splitlines() if _DEPRECATED.search(ln.split("#", 1)[0])]


assert deprecated_calls('export P="$(bashio::addon.ingress_port)"\n'), "the old name is found"
assert deprecated_calls("bashio::addons.installed\n"), "the old plural is found"
assert not deprecated_calls('export P="$(bashio::app.ingress_port)"\n# bashio::addon.port was the old name\n')

found = deprecated_calls(RUN_SH.read_text(encoding="utf-8"))
if found:
    print("deprecated bashio calls in run.sh:", found)
    sys.exit(1)
print("ALL OK")
