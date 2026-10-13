"""Golden-master test of routes/ignored.py: api_ignored_forget and _forget_mac, driven with fake requests and in-memory fake collaborators
(blocklist, history, newdevices lists, journal, dhcp, mDNS listener, logger, i18n) that RECORD every call. Per generated case the digest (sha1) of
response + status + recorded calls + final state is compared with tests/golden/ignored_forget_routes.json, written from the code as it was before the split.
Regenerate only on purpose:  IGNORED_GOLDEN_UPDATE=1 python tests/check_ignored_golden.py"""
import asyncio
import hashlib
import json
import os
import random
import sys
import types
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from fastapi import HTTPException  # noqa: E402
from app.routes import bodies, ignored  # noqa: E402
from app.storage import newdevices as real_newdevices  # noqa: E402

GOLDEN = Path(__file__).parent / "golden" / "ignored_forget_routes.json"
N = 2400
rng = random.Random(20261010)
STATS: dict = {}


def pick(seq):
    return seq[rng.randrange(len(seq))]


def count(key, cond=True):
    STATS[key] = STATS.get(key, 0) + (1 if cond else 0)


MACS = ["AA:BB:CC:00:00:01", "AA:BB:CC:00:00:02", "AA:BB:CC:00:00:03", "AA:BB:CC:00:00:04"]
RAW_MACS = MACS + ["aa-bb-cc-00-00-01", " aa:bb:cc:00:00:02 ", "aa:bb:cc:00:00:03", "00:00:00:00:00:00", "ff:ff:ff:ff:ff:ff", "01:00:5e:00:00:01", "zz", "", "  "]
IPS = ["192.168.1.21", "192.168.1.22", "192.168.1.23", "10.0.0.5"]


def _remove(items, iid):
    for n, i in enumerate(items):
        if i["id"] == iid:
            del items[n]
            return True
    return False


def make_world():
    log: list = []
    items = []
    for n in range(rng.randrange(0, 5)):
        kind = pick(["mac", "mac", "ip", "ip", "host", "name"])
        value = pick(RAW_MACS[:7] if kind == "mac" else IPS if kind == "ip" else ["tv", "phone", ""])
        items.append({"id": "i%d" % n, "kind": kind, "value": value, "label": pick(["", "TV", "Phone", None])})
    known = {}
    for mac in MACS:
        if rng.random() < 0.6:
            known[mac] = {"status": pick(["ignored", "ignored", "new", "known"]), "ip": pick(IPS + [None, ""]), "hostname": pick([None, "", "host-" + mac[-2:]])}
    dhcp_seen = {m.lower(): pick([{"hostname": "x"}, {"hostname": "y"}, {}]) for m in MACS if rng.random() < 0.4}
    by_mac = {m.lower(): pick([{"ip": pick(IPS)}, {"ip": None}, {}]) for m in MACS if rng.random() < 0.4}
    by_ip = {ip: {"mac": "x"} for ip in IPS if rng.random() < 0.4}

    bl = types.SimpleNamespace(
        list_items=lambda: (log.append(["bl.list"]), [dict(i) for i in items])[1],
        remove=lambda iid: (log.append(["bl.remove", iid]), _remove(items, iid))[1],
    )
    hist = types.SimpleNamespace(
        known_all=lambda: (log.append(["h.known_all"]), {k: dict(v) for k, v in known.items()})[1],
        known_delete=lambda mac: (log.append(["h.known_delete", mac]), known.pop(mac, None))[0],
    )
    nd = types.SimpleNamespace(
        normalize_mac=real_newdevices.normalize_mac,
        list_ignored=lambda h: (log.append(["nd.list_ignored", h is hist]), sorted(k for k, v in known.items() if v["status"] == "ignored"))[1],
    )
    jr = types.SimpleNamespace(add=lambda *a, **k: log.append(["journal.add", list(a), k]))
    lg = types.SimpleNamespace(info=lambda *a: log.append(["log.info", [str(x) for x in a]]))
    dh = types.SimpleNamespace(seen=dhcp_seen, _save=lambda: log.append(["dhcp._save"]))
    md = types.SimpleNamespace(by_mac=by_mac, by_ip=by_ip, _save=lambda: log.append(["mdns._save"]))
    i18n = types.SimpleNamespace(use_request=lambda r: log.append(["i18n.use_request"]), t=lambda key, **p: "T:" + key)
    state = {"items": items, "known": known, "dhcp": dhcp_seen, "by_mac": by_mac, "by_ip": by_ip}
    mods = dict(blocklist=bl, history=hist, newdevices=nd, journal=jr, logger=lg, dhcp=dh, mdns_listener=md, i18n=i18n)
    return log, state, mods


class FakeRequest:
    def __init__(self, body, mode):
        self.body, self.mode = body, mode

    async def json(self):
        if self.mode == "valueerror":
            raise ValueError("bad json")
        return self.body


def make_body(items):
    r = rng.random()
    if r < 0.42 and items:
        return {"id": pick(items)["id"]} if rng.random() < 0.9 else {"id": pick(items)["id"], "mac": pick(MACS)}
    if r < 0.5:
        return {"id": pick(["nope", "i99", "", 5, None])}
    if r < 0.88:
        return {"mac": pick(RAW_MACS)}
    if r < 0.92:
        return {"mac": pick([5, None, ["x"]])}
    if r < 0.96:
        return pick([{}, {"other": 1}, [], "str", 7, None])
    return {"id": pick(items)["id"] if items else "i0", "extra": 1}


def run_case():
    log, st, mods = make_world()
    saved = {k: getattr(ignored, k) for k in mods}
    saved_body_i18n = bodies.i18n                        # the body of the request is read by the shared helper, which asks the same (recorded) i18n
    for k, v in mods.items():
        setattr(ignored, k, v)
    bodies.i18n = mods["i18n"]
    try:
        mode = "valueerror" if rng.random() < 0.05 else "ok"
        body = make_body(st["items"])
        which = "forget" if rng.random() < 0.8 else "mac"
        try:
            if which == "forget":
                res = asyncio.run(ignored.api_ignored_forget(FakeRequest(body, mode)))
            else:
                res = ignored._forget_mac(pick(RAW_MACS))
        except HTTPException as exc:
            res = ["HTTP", exc.status_code, exc.detail]
        except Exception as exc:  # noqa: BLE001
            res = ["EXC", type(exc).__name__]
    finally:
        for k, v in saved.items():
            setattr(ignored, k, v)
        bodies.i18n = saved_body_i18n
    count("forget", which == "forget")
    count("mac_fn", which == "mac")
    count("http404", isinstance(res, list) and res[:2] == ["HTTP", 404])
    count("http400", isinstance(res, list) and res[:2] == ["HTTP", 400])
    count("dict_ok", isinstance(res, dict))
    count("true", res is True)
    count("false", res is False)
    count("journal", any(c[0] == "journal.add" for c in log))
    count("known_delete", any(c[0] == "h.known_delete" for c in log))
    count("dhcp_save", any(c[0] == "dhcp._save" for c in log))
    count("mdns_save", any(c[0] == "mdns._save" for c in log))
    count("bl_remove", any(c[0] == "bl.remove" for c in log))
    return {"which": which, "body": body, "mode": mode, "res": res, "log": log, "state": st}


def main():
    cases = [run_case() for _ in range(N)]
    digests = [hashlib.sha1(json.dumps(c, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest() for c in cases]
    sample = [cases[i] for i in range(0, N, N // 12)]
    for key, low in (("forget", 1500), ("mac_fn", 300), ("http404", 40), ("http400", 100), ("dict_ok", 600), ("true", 60), ("false", 60), ("journal", 500),
                     ("known_delete", 100), ("dhcp_save", 60), ("mdns_save", 60), ("bl_remove", 300)):
        assert STATS.get(key, 0) >= low, (key, STATS)
    new = {"n": N, "digests": digests, "sample": json.loads(json.dumps(sample, default=str))}
    if os.environ.get("IGNORED_GOLDEN_UPDATE") or not GOLDEN.exists():
        GOLDEN.parent.mkdir(exist_ok=True)
        GOLDEN.write_text(json.dumps(new, ensure_ascii=False), encoding="utf-8")
        print("golden written", GOLDEN.stat().st_size, "bytes", STATS)
    else:
        old = json.loads(GOLDEN.read_text(encoding="utf-8"))
        bad = [i for i, (a, b) in enumerate(zip(old["digests"], digests)) if a != b]
        assert old["n"] == N and not bad, ("differences at cases", bad[:5], json.dumps(cases[bad[0]], default=str)[:800] if bad else "")
    print("TUTTO OK")


main()
