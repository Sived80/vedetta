# SPDX-License-Identifier: GPL-3.0-only — additional terms in NOTICE
"""Where Vedetta runs: as an app of Home Assistant (under the Supervisor) or as a container of its own (Docker, for Home Assistant
Container), and the settings that change with it. One image serves both: the Supervisor gives every app SUPERVISOR_TOKEN, a plain
container has none. VEDETTA_MODE=addon|docker overrides the guess (tests, and a person who wants to be explicit).

Secrets (the Home Assistant token, the MQTT password) are read from a file first: VEDETTA_<NAME>_FILE, else /run/secrets/<name>
(Docker and Compose secrets), and only then from the variable VEDETTA_<NAME> itself, which `docker inspect` shows to anyone who can
run docker: allowed, but the log says once that a file is better. A secret is never logged, not even its length.

No import from the rest of the app (layer 0): applog and the HA modules use it."""
import os
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

ADDON, DOCKER = "addon", "docker"
SECRETS_DIR = Path("/run/secrets")
SUPERVISOR_WS = "ws://supervisor/core/websocket"
DEFAULT_PORT = 8765
_warned: set[str] = set()


def mode() -> str:
    """ADDON under the Supervisor, DOCKER otherwise (VEDETTA_MODE wins when it names one of the two)."""
    chosen = os.environ.get("VEDETTA_MODE", "").strip().lower()
    if chosen in (ADDON, DOCKER):
        return chosen
    return ADDON if os.environ.get("SUPERVISOR_TOKEN") else DOCKER


def is_docker() -> bool:
    return mode() == DOCKER


def secret(name: str, warn=None) -> str | None:
    """The secret NAME (lower case, e.g. "ha_token"): from VEDETTA_<NAME>_FILE, else /run/secrets/<name>, else VEDETTA_<NAME>.
    The content of a file is stripped of the spaces and line ends around it. None when there is none (or the file cannot be read).
    warn(text) is called once per secret taken from a plain variable."""
    var = "VEDETTA_" + name.upper()
    for path in (os.environ.get(var + "_FILE", "").strip(), str(SECRETS_DIR / name)):
        if path:
            value = _read(Path(path), name, warn)
            if value:
                return value
    value = os.environ.get(var, "").strip()
    if value and warn and name not in _warned:
        _warned.add(name)
        warn("%s comes from an environment variable: a secret file (%s_FILE or /run/secrets/%s) keeps it out of `docker inspect`" % (var, var, name))
    return value or None


def _read(path: Path, name: str = "", warn=None) -> str | None:
    """The content of a secret file; None when there is none. A file that exists but cannot be read is told once (with every capability
    dropped, root in the container cannot read a file of another user with mode 600: the usual mistake, and otherwise a silent one)."""
    try:
        return path.read_text(encoding="utf-8").strip() or None
    except PermissionError:
        if warn and ("unreadable:" + name) not in _warned:
            _warned.add("unreadable:" + name)
            warn("The secret file %s (%s) cannot be read: on the host make it owned by root, sudo chown root:root <file> && sudo chmod 600 <file>" % (path, name))
        return None
    except (OSError, UnicodeDecodeError):
        return None


def ha_token(warn=None) -> str | None:
    """The token for the Home Assistant API: the Supervisor's under it, else the long-lived access token the person made."""
    if mode() == ADDON:
        return os.environ.get("SUPERVISOR_TOKEN") or None
    return secret("ha_token", warn)


def ha_ws_url() -> str | None:
    """The websocket of Home Assistant: VEDETTA_HA_WS wins (tests); under the Supervisor its proxy; in Docker the one of VEDETTA_HA_URL
    (http://host:8123 -> ws://host:8123/api/websocket, https -> wss). None in Docker without an address: no Home Assistant."""
    if os.environ.get("VEDETTA_HA_WS"):
        return os.environ["VEDETTA_HA_WS"]
    if mode() == ADDON:
        return SUPERVISOR_WS
    return websocket_of(os.environ.get("VEDETTA_HA_URL", ""))


def websocket_of(url: str) -> str | None:
    """http(s)://host[:port][/path] -> ws(s)://host[:port][/path]/api/websocket; None for anything else (no scheme, another scheme,
    no host, user and password in the address: a token goes in its own file, never in a URL)."""
    try:
        parts = urlsplit((url or "").strip())
    except ValueError:
        return None
    if parts.scheme not in ("http", "https") or not parts.hostname or parts.username or parts.password or parts.query or parts.fragment:
        return None
    path = parts.path.rstrip("/")
    if path.endswith("/api/websocket"):
        path = path[: -len("/api/websocket")]
    return urlunsplit(("wss" if parts.scheme == "https" else "ws", parts.netloc, path + "/api/websocket", "", ""))


def port() -> int:
    """The port of the web page in Docker (VEDETTA_PORT, else DEFAULT_PORT). Under the Supervisor run.sh passes the ingress port."""
    try:
        value = int(os.environ.get("VEDETTA_PORT", ""))
        return value if 0 < value < 65536 else DEFAULT_PORT
    except ValueError:
        return DEFAULT_PORT
