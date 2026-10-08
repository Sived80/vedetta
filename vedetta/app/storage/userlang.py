"""The language each Home Assistant user chose in the menu (config/user_lang.json).

Home Assistant's ingress proxy puts the id of the logged-in user in the X-Remote-User-ID header (it removes any such header the client
sends, and the app only answers the Supervisor: VEDETTA_INGRESS_ONLY). With it the choice lives on the server, per person, and follows
them to every browser and device. The id is an opaque code that never leaves this file: it is not in the exports. At most MAX_USERS
people are remembered (the oldest choice goes first), so the file cannot grow without limit."""
import json
import os
import re
import tempfile

from ..paths import DATA_DIR as CONFIG_DIR

PATH = CONFIG_DIR / "user_lang.json"
MAX_USERS = 500
_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")

_cache: dict[str, str] | None = None


def valid_id(user_id: str | None) -> bool:
    return bool(user_id) and bool(_ID.match(user_id))


def _all() -> dict[str, str]:
    global _cache
    if _cache is None:
        try:
            raw = json.loads(PATH.read_text(encoding="utf-8"))
            _cache = {k: v for k, v in raw.items() if valid_id(k) and isinstance(v, str)} if isinstance(raw, dict) else {}
        except (OSError, ValueError):
            _cache = {}
    return _cache


def get(user_id: str | None) -> str | None:
    return _all().get(user_id) if valid_id(user_id) else None


def put(user_id: str | None, code: str | None) -> bool:
    """Remember the language of this user (code None: forget it, back to automatic). False if there is no valid id."""
    if not valid_id(user_id):
        return False
    data = _all()
    data.pop(user_id, None)          # a changed choice goes last: the oldest is the first to be dropped
    if code:
        data[user_id] = code
    while len(data) > MAX_USERS:
        data.pop(next(iter(data)))
    PATH.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=PATH.parent, prefix=".userlang-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f)
        os.replace(tmp, PATH)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)
    return True
