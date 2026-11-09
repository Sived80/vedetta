"""The networks written by the person, beyond the main one (networks.json): read, checked, changed under one lock and written atomically.

The main network is never stored: it is what the host says. A missing or unreadable file means no network written (the world is the main
network alone, exactly as before this file existed). Every row is checked again by networks.model.validate at every read, against the main
network of that moment: a row that no longer fits (the main network moved over it, a limit changed) is left out of the answer and kept in the
file, so that nothing written by the person is lost silently; the log says why.
Rows are kept as written (cidr as text, via as a sorted list, exclude as text): the file stays readable and a later version can read it."""
import functools
import json
import threading

from ..applog import logger
from ..atomic import write_atomic
from ..networks import model
from ..paths import DATA_DIR as CONFIG_DIR

NETWORKS_PATH = CONFIG_DIR / "networks.json"
FIELDS = ("id", "cidr", "via", "touch", "state", "exclude")

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


def _rows() -> list:
    """The rows of the file as written; [] when it is missing or not a list of objects."""
    try:
        data = json.loads(NETWORKS_PATH.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return []
    except (OSError, ValueError):
        logger.warning("networks.json illeggibile: nessuna rete in piu'")
        return []
    rows = data.get("networks") if isinstance(data, dict) else None
    return [r for r in rows if isinstance(r, dict)] if isinstance(rows, list) else []


def _save(rows: list) -> None:
    write_atomic(NETWORKS_PATH, lambda f: json.dump({"networks": rows}, f, indent=1), ".networks-", folder=CONFIG_DIR)
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
        row["via"] = sorted(row["via"])
    row.setdefault("touch", "presence")
    row.setdefault("state", "proposed")
    row.setdefault("exclude", [])
    return row


@_locked
def add(candidate, main: model.Network) -> model.Network:
    """Check a new network against the main one and the written ones, and store it. Rejected (with its code) when it does not fit."""
    if not isinstance(candidate, dict):
        raise model.Rejected("E_SHAPE")
    row = _row(candidate)
    network = model.validate(row, [main, *load(main)])
    rows = _rows()
    if any(r.get("id") == network.id for r in rows):      # a row left out by load() still owns its id
        raise model.Rejected("E_DUP_ID")
    _save([*rows, row])
    return network


@_locked
def change(nid: str, fields: dict, main: model.Network) -> model.Network | None:
    """Change the touch, state or excluded ranges of a written network; None when there is no such network. Rejected when the result does not fit."""
    rows = _rows()
    index = next((i for i, r in enumerate(rows) if r.get("id") == nid), None)
    if index is None:
        return None
    row = _row({**rows[index], **{k: v for k, v in fields.items() if k in ("touch", "state", "exclude")}})
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
