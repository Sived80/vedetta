# SPDX-License-Identifier: GPL-3.0-only — additional terms in NOTICE
"""The password hash and the open sessions, on disk.

- /data/auth.json: {"password": "<scrypt$...>", "changed_at": <time>}; nothing else.
- /data/sessions.json: {"<sha256 of the session id>": {"created": t, "seen": t}}. The id itself lives only in the cookie of the
  browser: the file, a backup or an export of it cannot open a session (OWASP Session Management: store a digest).

Both files are written atomically, readable by their owner only (0600: mkstemp), and are never part of an export (export/: the
files it reads are named one by one, and the final check refuses a "scrypt$" text). A session ends after IDLE_S without a request
or ABSOLUTE_S after the login, at the logout, and for every session when the password changes. At most MAX_SESSIONS stay (the
oldest go first). A lock guards the in-memory copy: the requests of the page arrive in parallel."""
import hashlib
import json
import secrets
import threading
import time

from ..atomic import write_atomic
from ..paths import DATA_DIR

AUTH_PATH = DATA_DIR / "auth.json"
SESSIONS_PATH = DATA_DIR / "sessions.json"
IDLE_S = 12 * 3600
ABSOLUTE_S = 30 * 24 * 3600
MAX_SESSIONS = 20
SEEN_WRITE_S = 300            # the time of the last request is written at most every 5 minutes (not at each request)
_lock = threading.RLock()
_sessions: dict[str, dict] | None = None


def _digest(session_id: str) -> str:
    return hashlib.sha256(session_id.encode("utf-8")).hexdigest()


def _read(path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _write(path, data: dict) -> None:
    write_atomic(path, lambda f: json.dump(data, f), "." + path.stem + "-")


# ---- the password

def password_hash() -> str | None:
    """The stored form of the password; None before the first setup."""
    value = _read(AUTH_PATH).get("password")
    return value if isinstance(value, str) and value.startswith("scrypt$") else None


def has_password() -> bool:
    return password_hash() is not None


def set_password_hash(stored: str) -> None:
    """Saves a new password hash and closes every session (the old password, or whoever knew it, is out)."""
    with _lock:
        _write(AUTH_PATH, {"password": stored, "changed_at": int(time.time())})
        drop_all()


# ---- the sessions

def _stamp() -> tuple:
    """When the two files last changed: the command that sets the password runs in another process (docker exec), and the sessions it
    closes must close here at once, not at the next restart."""
    out = []
    for path in (AUTH_PATH, SESSIONS_PATH):
        try:
            out.append(path.stat().st_mtime_ns)
        except OSError:
            out.append(None)
    return tuple(out)


_seen_stamp: tuple | None = None


def _all() -> dict[str, dict]:
    global _sessions, _seen_stamp
    stamp = _stamp()
    if _sessions is None or stamp != _seen_stamp:
        raw = _read(SESSIONS_PATH)
        _sessions = {k: v for k, v in raw.items() if isinstance(k, str) and len(k) == 64 and isinstance(v, dict)}
        _seen_stamp = stamp
    return _sessions


def _alive(row: dict, now: float) -> bool:
    created, seen = row.get("created", 0), row.get("seen", 0)
    return isinstance(created, (int, float)) and isinstance(seen, (int, float)) and now - created < ABSOLUTE_S and now - seen < IDLE_S


def new_session() -> str:
    """A new session (a new id at every login: OWASP, against session fixation). Returns the id for the cookie."""
    session_id = secrets.token_urlsafe(32)
    now = int(time.time())
    with _lock:
        rows = {k: v for k, v in _all().items() if _alive(v, now)}
        rows[_digest(session_id)] = {"created": now, "seen": now}
        if len(rows) > MAX_SESSIONS:
            rows = dict(sorted(rows.items(), key=lambda kv: kv[1]["seen"])[-MAX_SESSIONS:])
        _replace(rows)
    return session_id


def valid(session_id: str | None) -> bool:
    """True for an open session; it also notes the time of this request (for the idle limit)."""
    if not session_id or len(session_id) > 128:
        return False
    key, now = _digest(session_id), int(time.time())
    with _lock:
        rows = _all()
        row = rows.get(key)
        if row is None:
            return False
        if not _alive(row, now):
            rows.pop(key, None)
            _replace(rows)
            return False
        if now - row["seen"] >= SEEN_WRITE_S:
            row["seen"] = now
            _replace(rows)
        return True


def drop(session_id: str | None) -> None:
    """The logout: this session is closed on the server, not only forgotten by the browser."""
    if not session_id:
        return
    with _lock:
        rows = _all()
        if rows.pop(_digest(session_id), None) is not None:
            _replace(rows)


def drop_all() -> None:
    with _lock:
        _replace({})


def _replace(rows: dict) -> None:
    global _sessions, _seen_stamp
    _sessions = rows
    _write(SESSIONS_PATH, rows)
    _seen_stamp = _stamp()


def forget_cache() -> None:
    """Reads the files again at the next call (the command that changes the password runs in another process; the tests too)."""
    global _sessions
    with _lock:
        _sessions = None
