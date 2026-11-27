# SPDX-License-Identifier: GPL-3.0-only — additional terms in NOTICE
"""The networks written by the person, beyond the main one (networks.json): read, checked, changed under one lock and written atomically.

The main network is never stored: it is what the host says. A missing or unreadable file means no network written (the world is the main
network alone, exactly as before this file existed). Every row is checked again by networks.model.validate at every read, against the main
network of that moment: a row that no longer fits (the main network moved over it, a limit changed) is left out of the answer and kept in the
file, so that nothing written by the person is lost silently; the log says why.
Rows are kept as written (cidr as text, via as a sorted list, exclude as text): the file stays readable and a later version can read it.
The name of the main network (the only thing about it the person writes) is kept apart, in "main": a version that does not know it reads
"networks" only and ignores the rest; so does it with the fields "name" and "vlan" of a row (going back one version loses the names, nothing else)."""
import functools
import json
import threading

from ..applog import logger
from ..atomic import write_atomic
from ..networks import model
from ..paths import DATA_DIR as CONFIG_DIR

NETWORKS_PATH = CONFIG_DIR / "networks.json"
FIELDS = ("id", "cidr", "via", "touch", "state", "exclude", "name", "vlan")
CHANGEABLE = ("touch", "state", "exclude", "name", "vlan")

_LOCK = threading.RLock()       # one lock for every read - modify - write of the file
_cache: dict = {"key": None, "value": ()}


def _locked(function):
    @functools.wraps(function)
    def run(*args, **kwargs):
        with _LOCK:
            return function(*args, **kwargs)
    return run


def _stamp():
    try:
        st = NETWORKS_PATH.stat()
    except OSError:
        return None
    return st.st_mtime_ns, st.st_size


def rows() -> list:
    """The rows of the file as written, those left out by load() included (the panel says which)."""
    with _LOCK:
        return _rows()


def _data() -> dict:
    """The whole file; {} when it is missing, unreadable or not an object."""
    try:
        data = json.loads(NETWORKS_PATH.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, ValueError):
        logger.warning("networks.json illeggibile: nessuna rete in piu'")
        return {}
    return data if isinstance(data, dict) else {}


def _rows() -> list:
    """The rows of the file as written; [] when it is missing or not a list of objects."""
    rows = _data().get("networks")
    return [r for r in rows if isinstance(r, dict)] if isinstance(rows, list) else []


def _main_part() -> dict:
    part = _data().get("main")
    return part if isinstance(part, dict) else {}


def _save(rows: list, main_part: dict | None = None) -> None:
    """Write the rows; the part of the main network stays as it is unless a new one is given (an empty one is not written)."""
    part = _main_part() if main_part is None else main_part
    data = {"networks": rows, **({"main": part} if part else {})}
    write_atomic(NETWORKS_PATH, lambda f: json.dump(data, f, indent=1), ".networks-", folder=CONFIG_DIR)
    _cache["key"] = None


def _checked(rows: list, main: model.Network) -> tuple:
    kept: list = []
    for row in rows:
        try:
            kept.append(model.validate(row, [main, *kept]))
        except model.Rejected as exc:
            logger.warning("Rete %s lasciata fuori: %s", row.get("cidr"), exc.code)
    return tuple(kept)


@_locked
def load(main: model.Network) -> tuple:
    """The written networks that fit now next to `main`, in the order of the file. Read again only when the file or the main network changed."""
    key = (_stamp(), str(main.cidr))
    if key[0] is None:
        return ()
    if _cache["key"] != key:
        _cache["key"], _cache["value"] = key, _checked(_rows(), main)
    return _cache["value"]


def _row(candidate: dict) -> dict:
    """The fields of a candidate, as they are stored: only the known ones, via sorted, the defaults written out."""
    row = {k: candidate[k] for k in FIELDS if k in candidate}
    if isinstance(row.get("via"), (list, tuple, set, frozenset)):
        row["via"] = sorted(row["via"], key=repr)      # repr: a list of mixed things sorts too, and model.validate refuses it (never a 500)
    row.setdefault("touch", "presence")
    row.setdefault("state", "proposed")
    row.setdefault("exclude", [])
    for optional in ("name", "vlan"):          # no name, no VLAN: not written at all, as in a file of the version before
        if row.get(optional) in (None, ""):
            row.pop(optional, None)
    return row


def _checked_new(candidate, main: model.Network) -> tuple:
    if not isinstance(candidate, dict):
        raise model.Rejected("E_SHAPE")
    row = _row(candidate)
    network = model.validate(row, [main, *load(main)])
    rows = _rows()
    if any(r.get("id") == network.id for r in rows):      # a row left out by load() still owns its id
        raise model.Rejected("E_DUP_ID")
    return network, row, rows


@_locked
def check(candidate, main: model.Network) -> model.Network:
    """The network a candidate would be, checked exactly as add() checks it, and not stored («try and add»)."""
    return _checked_new(candidate, main)[0]


@_locked
def add(candidate, main: model.Network) -> model.Network:
    """Check a new network against the main one and the written ones, and store it. Rejected (with its code) when it does not fit."""
    network, row, rows = _checked_new(candidate, main)
    _save([*rows, row])
    return network


@_locked
def change(nid: str, fields: dict, main: model.Network) -> model.Network | None:
    """Change the touch, state, excluded ranges, name or VLAN of a written network; None when there is no such network. Rejected when the result does not fit."""
    rows = _rows()
    index = next((i for i, r in enumerate(rows) if r.get("id") == nid), None)
    if index is None:
        return None
    row = _row({**rows[index], **{k: v for k, v in fields.items() if k in CHANGEABLE}})
    others = [n for n in load(main) if n.id != nid]
    network = model.validate(row, [main, *others])
    rows[index] = row
    _save(rows)
    return network


@_locked
def remove(nid: str) -> bool:
    """Forget a written network; False when there is no such network."""
    rows = _rows()
    kept = [r for r in rows if r.get("id") != nid]
    if len(kept) == len(rows):
        return False
    _save(kept)
    return True


@_locked
def main_name() -> str | None:
    """The name the person gave the main network, or None (the panel then shows its own default name). A bad value in the file is no name."""
    try:
        return model.name_of(_main_part().get("name"))
    except model.Rejected:
        return None


@_locked
def set_main_name(value) -> None:
    """Give the main network a name (None or "" take it away). Rejected with E_BAD_NAME, as the name of any network."""
    name = model.name_of(value)
    part = {k: v for k, v in _main_part().items() if k != "name"}
    if name is not None:
        part["name"] = name
    _save(_rows(), part)
