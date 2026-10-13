"""Reading of the JSON files shipped with the app (app/data/*.json: kinds of device, Home Assistant integrations, brand logos, product signatures).

A file that cannot be read (missing, not JSON, without the key asked) must not empty the recognition without a trace: it is told once per file in the log, at warning level,
and the answer is the `default` of the caller (its own empty value), so that the service goes on. What the file holds under the key is returned as it is, even a null. A file that is JSON but not an object is a broken build, not a missing file: it stops loudly (TypeError), as it always did."""
from pathlib import Path

from .applog import logger

DATA_DIR = Path(__file__).resolve().parent / "data"
_told: set = set()      # the files already reported: a table is read once, but a reader may ask again after a failure


def read(path: Path, key: str, *, what: str, default=None):
    """The value under `key` in the JSON file at `path`; `default` (and one warning for that file) when it cannot be read. `what` names the table in the warning."""
    import json
    try:
        return json.loads(path.read_text(encoding="utf-8"))[key]
    except (OSError, ValueError, KeyError) as exc:
        if path not in _told:
            _told.add(path)
            logger.warning("%s not readable (%s: %s): what depends on it is empty", what, path.name, exc.__class__.__name__)
        return default
