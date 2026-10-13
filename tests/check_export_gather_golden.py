"""Golden-master test of export_engine._gather_data_files (the data folder -> text files of the export, with the manifest notes) and export_engine._gather_device_debug_and_focus (per-device debug
and evidence, plus the "device under examination" section): generated runs with the collaborators replaced by deterministic in-memory ones that RECORD THEIR CALLS - a real temporary data
folder (valid, invalid, binary, credential-like, empty and oversized files, a subfolder, the database and mapping files, a missing folder), a fake shared state (service diagnostics that may
fail), fake log/journal period filters (one of which fails on a marker), a fake device_debug / evidence summary / flagged-device list / compact card / history (each failing for some
devices), a frozen clock - must give exactly the manifest, the files added (in order), the return values and the ORDER and arguments of every call, stored as a sha1 digest per case plus a
small readable sample in tests/golden/export_gather.json, written from the code as it was before the functions were split.
Regenerate only on purpose:  EXPGATHER_GOLDEN_UPDATE=1 python tests/check_export_gather_golden.py"""
import hashlib
import json
import os
import random
import shutil
import sys
import tempfile
import time as real_time
import types
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app.export import export_engine as ee, export_gather  # noqa: E402
import app.storage.history as history_module  # noqa: E402

GOLDEN = Path(__file__).parent / "golden" / "export_gather.json"
rng = random.Random(86420)
STATS: dict = {}
LEGACY = ee.legacy
LEGACY.MAX_LOG_BYTES = 64


def pick(seq):
    return seq[rng.randrange(len(seq))]


def dig(obj) -> str:
    return hashlib.sha1(json.dumps(obj, ensure_ascii=False, default=str).encode("utf-8")).hexdigest()


def count(key, cond):
    STATS[key] = STATS.get(key, 0) + (1 if cond else 0)


class FakePrepared:
    """The part of Prepared that the gathering uses: the period, the manifest, the files and `add` (a text file of the export; into `added` when it is given)."""

    def __init__(self, m, since, until, added=None):
        self.files, self.manifest, self.since, self.until, self._added = {}, m, since, until, added

    def add(self, name, text):
        if self._added is not None:
            self._added.append([name, text])
        else:
            self.files[name] = ["text", text]


# ---------------- _gather_data_files ----------------
FILE_NAMES = ["a.json", "devices.json", "bad.json", "list.json", "x.log", "app.log", "e.jsonl", "events.jsonl", "notes.txt", "bin.dat", "binlog.log", "vedetta.db", "vedetta.db-wal",
              "export_mapping.local", "api_key.json", "my_token.txt", "PASSWD.log", "user_lang.json", "noext", "data.JSON", "Secret.jsonl", "cfg.yaml", "Zeta.txt", "Beta.json", "Alpha.log"]
JSON_BODIES = ['{"name": "café"}'.encode("utf-8"),b'{"name": "x", "api_key": "abc", "nested": {"password": "p", "ok": 1}}', b'[1, {"token": "t"}]', b"{bad", b"", b"3", b'{"user_lang": "it", "k": ""}', b"\xff\xfe{}"]
LINES = [b"2026-10-01 10:00:00 INFO start", b"2026-10-02 11:00:00 WARNING x " + b"y" * 30, b'{"ts": 5, "a": 1}', b"BOOM line", b"\xff\xfe broken", b"plain"]


def body_for(name):
    if name.lower().endswith(".json") or name.endswith(".yaml"):
        return pick(JSON_BODIES)
    if name.endswith(".log") or name.endswith(".jsonl"):
        return b"\n".join(pick(LINES) for _ in range(rng.randrange(0, 6)))
    return pick([b"hello", b"\x00\x01\xff\xfe", b"", "café".encode("utf-8")])


def case_data_files():
    log: list = []
    root = Path(tempfile.mkdtemp(prefix="vedetta-gather-test-"))
    try:
        if rng.random() < 0.08:
            data_dir = root / "missing"
        else:
            data_dir = root
            for name in rng.sample(FILE_NAMES, rng.randrange(0, 9)):
                (data_dir / name).write_bytes(body_for(name))
            if rng.random() < 0.3:
                (data_dir / "sub").mkdir()
        mode = rng.random()

        def diagnostics():
            log.append(["diagnostics"])
            if mode < 0.2:
                raise RuntimeError("diag down")
            return {"files": 3}

        ee.state = types.SimpleNamespace(merge_report=pick([None, {"merged": 2}, []]), diagnostics=diagnostics)
        export_gather.state = ee.state

        def filter_log(text, since, until):
            log.append(["filter_log", text, since, until])
            if "BOOM" in text:
                raise ValueError("bad log")
            return "L:" + text

        def filter_jsonl(text, since, until):
            log.append(["filter_jsonl", text, since, until])
            if "BOOM" in text:
                raise ValueError("bad jsonl")
            return "J:" + text

        ee.filter_log, ee.filter_jsonl = filter_log, filter_jsonl
        export_gather.filter_log, export_gather.filter_jsonl = ee.filter_log, ee.filter_jsonl
        since = pick([None, None, 1000.0, 5.5, 0.0])
        until = pick([None, 2000.0, 9.5])
        m = {} if rng.random() < 0.03 else {"notes": [], "x": 1}
        p = FakePrepared(m, since, until)
        try:
            ee._gather_data_files(p, data_dir)
            add = p.add
            add("zz", "tail")
            res = {"add_ok": callable(add), "last": list(p.files.items())[-1]}
        except Exception as exc:
            res = {"exc": type(exc).__name__}
        res.update({"m": m, "files": list(p.files.items()), "log": log})
        count("df_notes", bool(m.get("notes")))
        count("df_files", len(p.files) >= 3)
        count("df_since", since is not None and len(p.files) >= 2)
        count("df_exc", "exc" in res)
        count("df_binary", any("binary" in n for n in m.get("notes", [])))
        count("df_filter", any(e[0] == "filter_log" for e in log) and any(e[0] == "filter_jsonl" for e in log))
        count("df_tail", since is None and any(isinstance(v, list) and v[1].startswith("L") is False and name.endswith(".log") for name, v in p.files.items()))
        return res
    finally:
        shutil.rmtree(root, ignore_errors=True)


# ---------------- _gather_device_debug_and_focus ----------------
FROZEN = 1_700_000_000.0


def case_focus():
    log: list = []
    ids = rng.sample(["d1", "d2", "d3", "d4", "d5", "d6"], rng.randrange(0, 6))
    devices = {d: pick([{"name": "N" + d, "ip": "10.0.0." + d[-1]}, {"name": None}, {}, {"ip": "1.1.1.1"}]) for d in ids}
    dmode = {d: pick(["ok", "ok", "ok", "raise", "none"]) for d in ids}
    smode = {d: pick(["ok", "ok", "raise", "none"]) for d in ids}
    cfgs = []
    for _ in range(rng.randrange(0, 9)):
        c = {} if rng.random() < 0.05 else {"id": pick(ids + ["ghost"]) if ids else "ghost"}
        if rng.random() < 0.75:
            c["focus"] = pick([True, True, False, 0, 1])
        if rng.random() < 0.6:
            c["focus_note"] = pick(["", "note", None, "why"])
        cfgs.append(c)
    since = pick([None, None, 1000.0, 50.0, 0.0])
    until = pick([None, 1000.0, 1050.0, 86400.0 * 2, 0.0, 1000.0 + 86400 * 0.4, 1000.0 + 86400 * 3.6, 1000.0 + 86400 * 5.5, 40.0, 2000.0])
    load_fail = rng.random() < 0.08
    hist_fail = {d for d in ids if rng.random() < 0.15}
    card_fail = {d for d in ids if rng.random() < 0.1}

    ee.state = types.SimpleNamespace(devices=devices)
    export_gather.state = ee.state

    def device_debug_(did):
        log.append(["device_debug", did])
        if dmode[did] == "raise":
            raise KeyError(did)
        return None if dmode[did] == "none" else {"debug_of": did}

    def summarize(debug, dev):
        log.append(["summarize", debug, dev])
        d = (debug or {}).get("debug_of", "none")
        if smode.get(d) == "raise":
            raise ValueError("sum " + d)
        return None if smode.get(d) == "none" else {"evidence_of": d}

    def compact_device(dev, cfg):
        log.append(["compact_device", dev, cfg])
        if cfg.get("id") in card_fail:
            raise RuntimeError("card")
        return {"card": cfg.get("id"), "focus_note": "x", "k": 1}

    def load_devices():
        log.append(["load_devices"])
        if load_fail:
            raise OSError("cannot read")
        return cfgs

    class FakeHistory:
        def device_focus(self, did, h_since):
            log.append(["device_focus", did, h_since])
            if did in hist_fail:
                raise RuntimeError("hist")
            return {"events": len(did)}

    ee.evidence = types.SimpleNamespace(summarize=summarize)
    export_gather.evidence = ee.evidence
    ee.devices_config = types.SimpleNamespace(load_devices=load_devices, FOCUS_MAX=ee.devices_config.FOCUS_MAX)
    export_gather.devices_config = ee.devices_config
    ee.time = types.SimpleNamespace(time=lambda: (log.append(["time"]), FROZEN)[1], strftime=real_time.strftime)
    export_gather.time = ee.time
    saved_hist = history_module.history
    history_module.history = FakeHistory()
    ha_data_ = types.SimpleNamespace(compact_device=compact_device)
    m = {} if rng.random() < 0.03 else {"notes": []}
    added: list = []
    try:
        try:
            res = ee._gather_device_debug_and_focus(FakePrepared(m, since, until, added), device_debug_, ha_data_)
            out = {"ret": res}
        except Exception as exc:
            out = {"exc": type(exc).__name__}
        out.update({"m": m, "added": added, "log": log})
    finally:
        history_module.history = saved_hist
    count("fc_focus", "focus" in m and m["focus"]["devices"] > 0)
    count("fc_many", "focus" in m and m["focus"]["devices"] >= 3)
    count("fc_note", "focus" in m and m["focus"]["with_note"] > 0)
    count("fc_notes", any("focus:" in n for n in m.get("notes", [])))
    count("fc_err", any("error" in v for v in out.get("ret", [{}])[0].values()) if out.get("ret") else False)
    count("fc_since", since is not None and "focus" in m)
    count("fc_exc", "exc" in out)
    count("fc_days", "focus" in m and m["focus"]["days"] not in (14,))
    return out


def main():
    res, samples = {}, {}
    for name, fn, n in (("data", case_data_files, 1500), ("focus", case_focus, 3000)):
        res[name], samples[name] = [], []
        for i in range(n):
            r = fn()
            res[name].append(dig(r))
            if i < 4:
                samples[name].append(r)
    return {"digests": res, "samples": samples}


out = json.loads(json.dumps(main(), ensure_ascii=False, default=str))
if os.environ.get("EXPGATHER_GOLDEN_UPDATE") or not GOLDEN.exists():
    GOLDEN.write_text(json.dumps(out, indent=0), encoding="utf-8")
    print("golden written")
want = json.loads(GOLDEN.read_text(encoding="utf-8"))
for part in ("data", "focus"):
    a, b = out["digests"][part], want["digests"][part]
    assert len(a) == len(b), part
    for i, (x, y) in enumerate(zip(a, b)):
        assert x == y, "%s case %d differs" % (part, i)
assert out["samples"] == want["samples"]
s = STATS
for k in ("df_notes", "df_files", "df_since", "df_binary", "df_filter", "df_tail", "fc_focus", "fc_many", "fc_note", "fc_notes", "fc_err", "fc_since", "fc_days"):
    assert s.get(k, 0) > 40, (k, s)
assert s.get("df_exc", 0) > 10 and s.get("fc_exc", 0) > 10, s
print("TUTTO OK")
