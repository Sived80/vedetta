"""The version that the page shows when the server does not tell it (FALLBACK_VERSION in the front end) is the version of the release: a release that forgets to update it shows the old number
(the 0.9.0 went out with "0.8.0" there). It is compared with vedetta/VERSION and with the version of the add-on in vedetta/config.yaml."""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
version = (ROOT / "vedetta" / "VERSION").read_text(encoding="utf-8").strip()
config = re.search(r'^version:\s*"?([^"\s]+)"?', (ROOT / "vedetta" / "config.yaml").read_text(encoding="utf-8"), re.M).group(1)
page = (ROOT / "vedetta" / "app" / "frontend" / "ha" / "js" / "filters.js").read_text(encoding="utf-8")
found = re.findall(r'var FALLBACK_VERSION = "([^"]*)";', page)

assert len(found) == 1, "exactly one FALLBACK_VERSION in filters.js, found %r" % found
assert config == version, "vedetta/config.yaml says %s and vedetta/VERSION says %s" % (config, version)
assert found[0] == version, "FALLBACK_VERSION is %s and the release is %s: update it in vedetta/app/frontend/ha/js/filters.js" % (found[0], version)
print("TUTTO OK")
sys.exit(0)
