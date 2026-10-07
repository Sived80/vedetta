"""Digest of a Vedetta export: opens the encrypted report (.txt) or the plain zip and prints where to look first.

    python tools/riepilogo_report.py vedetta-report-ab12cd.txt            # decrypts with ~/.vedetta/report_private.key
    python tools/riepilogo_report.py vedetta-analisi-20261007-120000.zip  # a plain zip
    python tools/riepilogo_report.py report.txt --device iPhone-2         # one card: its data, history, MACs
    python tools/riepilogo_report.py report.txt --json                    # the same digest as JSON

Nothing is written to disk: the zip stays in memory, the history database is read from a temporary copy that is deleted.
The report is untrusted data: only known files are read, with a size limit, and nothing is executed."""
import argparse
import io
import json
import re
import sqlite3
import sys
import tempfile
import time
import zipfile
from collections import Counter
from datetime import datetime, timezone, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
MAX_FILE = 64 * 1024 * 1024          # a single file in the zip is never read above this size
LOW = 40                              # certainty (percent) under which a name / brand / group is "weak"
GROUPS_NEUTRAL = {"generic", "other", "altro"}      # the group "Other devices"


def load_zip(path: Path, key: Path | None) -> zipfile.ZipFile:
    raw = path.read_bytes()
    if raw[:2] == b"PK":
        return zipfile.ZipFile(io.BytesIO(raw))
    from open_report import open_report                      # the same function the author uses for the .txt
    key_path = key or Path.home() / ".vedetta" / "report_private.key"
    return zipfile.ZipFile(io.BytesIO(open_report(raw.decode("ascii", "strict"), key_path.read_text(encoding="ascii"))))


def read(z: zipfile.ZipFile, name: str):
    try:
        info = z.getinfo(name)
    except KeyError:
        return None
    if info.file_size > MAX_FILE:
        return None
    return z.read(name)


def read_json(z: zipfile.ZipFile, name: str, default=None):
    data = read(z, name)
    if data is None:
        return default
    try:
        return json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return default


def open_db(z: zipfile.ZipFile):
    data = read(z, "data/vedetta.db")
    if not data:
        return None, None
    tmp = tempfile.TemporaryDirectory()
    path = Path(tmp.name) / "v.db"
    path.write_bytes(data)
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    return con, tmp


def local_time(ts, offset: str | None) -> str:
    try:
        sign = -1 if (offset or "+0000").startswith("-") else 1
        off = timezone(timedelta(hours=sign * int(offset[1:3]), minutes=sign * int(offset[3:5]))) if offset else timezone.utc
        return datetime.fromtimestamp(float(ts), off).strftime("%d/%m %H:%M")
    except Exception:
        return "?"


def devices_of(z):
    comp = read_json(z, "state/devices_compact.json", [])
    return comp if isinstance(comp, list) else list(comp.get("devices", comp).values()) if isinstance(comp, dict) else []


def digest(z: zipfile.ZipFile) -> dict:
    man = read_json(z, "manifest.json", {}) or {}
    off = (man.get("time") or {}).get("utc_offset")
    devs = devices_of(z)
    ev = read_json(z, "state/evidence.json", {}) or {}
    out: dict = {"manifest": {k: man.get(k) for k in ("version", "created", "platform", "time", "deep_search", "omitted", "lines_removed", "phone_merge")}}
    # --- devices
    groups = Counter(d.get("type") or "?" for d in devs)
    out["devices"] = {"total": len(devs), "online": sum(1 for d in devs if d.get("online")), "by_group": dict(groups.most_common())}
    weak = []
    for d in devs:
        e = ev.get(d.get("id")) or {}
        cert = {k: (e.get(k) or {}).get("certainty") for k in ("name", "brand", "group")}
        named_by_ip = (e.get("name") or {}).get("basis") == "ip" or d.get("name") == d.get("ip")
        low = [k for k, c in cert.items() if c is not None and c < LOW and not (k == "brand" and not d.get("brand")) and not (k == "name" and named_by_ip)]
        if (d.get("type") in GROUPS_NEUTRAL) or low:
            weak.append({"id": d.get("id"), "name": d.get("name"), "ip": d.get("ip"), "group": d.get("type"), "brand": d.get("brand"), "weak": low or ["group"], "certainty": cert})
    out["weak"] = sorted(weak, key=lambda w: (w["group"] not in GROUPS_NEUTRAL, w["name"] or ""))
    out["ip_named"] = sum(1 for d in devs if d.get("name") == d.get("ip"))
    out["no_mac"] = [d.get("name") for d in devs if not d.get("mac")]
    dup = Counter(d.get("name") for d in devs)
    out["same_name"] = {n: c for n, c in dup.items() if c > 1 and n}
    # --- history
    con, tmp = open_db(z)
    hist: dict = {}
    if con is not None:
        try:
            tables = {r[0] for r in con.execute("select name from sqlite_master where type='table'")}
            if "presence_events" in tables:
                lo, hi = con.execute("select min(ts), max(ts) from presence_events").fetchone()
                hist["presence"] = {"from": local_time(lo, off) if lo else None, "to": local_time(hi, off) if hi else None}
                flaps = con.execute("select device_id, count(*) n from presence_events group by device_id order by n desc limit 8").fetchall()
                hist["most_flapping"] = [(r["device_id"], r["n"]) for r in flaps]
                macs = con.execute("select device_id, count(distinct mac) n from presence_events where mac is not null group by device_id having n > 1 order by n desc limit 8").fetchall()
                hist["several_macs"] = [(r["device_id"], r["n"]) for r in macs]
            if "scans" in tables:
                lo, hi = con.execute("select min(ts), max(ts) from scans").fetchone()
                hist["scans"] = {"count": con.execute("select count(*) from scans").fetchone()[0], "from": local_time(lo, off) if lo else None, "to": local_time(hi, off) if hi else None}
                by_hour = Counter(local_time(r[0], off)[6:8] for r in con.execute("select ts from scans"))
                hist["scans_by_hour"] = dict(sorted(by_hour.items()))
            if "mac_takeover" in tables:
                rows = con.execute("select device_id, count(*) n, sum(new_known) k from mac_takeover group by device_id order by n desc limit 8").fetchall()
                hist["mac_changes"] = [(r["device_id"], r["n"], r["k"]) for r in rows]
                hist["mac_changes_total"] = con.execute("select count(*) from mac_takeover").fetchone()[0]
            if "mac_memory" in tables:
                hist["macs_known"] = con.execute("select count(*) from mac_memory").fetchone()[0]
        finally:
            con.close()
            tmp.cleanup()
    out["history"] = hist
    # --- log
    log = read(z, "data/dashboard.log")
    if log:
        lines = log.decode("utf-8", "replace").split("\n")
        stamp = [l.split("\t", 1)[0] for l in lines if l.startswith("20")]
        levels = Counter(l.split("\t")[1] for l in lines if l.count("\t") >= 2)
        msgs = Counter(re.sub(r"\d+(\.\d+){0,3}", "N", l.split("\t", 2)[2])[:90] for l in lines if l.count("\t") >= 2 and l.split("\t")[1] in ("WARNING", "ERROR"))
        out["log"] = {"lines": len(lines), "from": stamp[0][:16] if stamp else None, "to": stamp[-1][:16] if stamp else None, "levels": dict(levels), "top_problems": msgs.most_common(6)}
    return out


def card(z, key: str) -> dict:
    devs = devices_of(z)
    sel = [d for d in devs if key.lower() in {str(d.get("name", "")).lower(), str(d.get("id", "")).lower(), str(d.get("ip", "")).lower()} or str(d.get("ip", "")).endswith("." + key)]
    ev = read_json(z, "state/evidence.json", {}) or {}
    dbg = read_json(z, "state/devices_debug.json", {}) or {}
    res = []
    for d in sel:
        res.append({"card": {k: d.get(k) for k in ("id", "name", "ip", "mac", "vendor", "brand", "type", "online", "is_mobile", "name_source")},
                    "ports": [p.get("label") for p in d.get("ports") or []], "attrs": {a["key"]: a["value"] for a in d.get("attrs") or []},
                    "evidence": ev.get(d.get("id")), "debug_keys": sorted(((dbg.get(d.get("id")) or {}).get("debug") or {}).keys())})
    return {"matches": res}


def show(dg: dict) -> None:
    m = dg["manifest"]
    print(f"Vedetta {m.get('version')} · creato {m.get('created')} · {m.get('platform')}")
    t = m.get("time") or {}
    print(f"Fuso {t.get('utc_offset')} (da HA: {t.get('from_home_assistant')}) · notte alle {t.get('night_hour')}:00 · mai analizzati a fondo: {(m.get('deep_search') or {}).get('never_analysed')}")
    if m.get("omitted"):
        print("FILE LASCIATI FUORI:", m["omitted"])
    if m.get("lines_removed"):
        print("RIGHE TOLTE:", m["lines_removed"])
    d = dg["devices"]
    print(f"\nDispositivi: {d['total']} ({d['online']} online)  ·  " + ", ".join(f"{g}: {n}" for g, n in d["by_group"].items()))
    if dg.get("ip_named"):
        print(f"  {dg['ip_named']} dispositivi hanno solo l'IP come nome")
    if dg["weak"]:
        print(f"\nDa guardare (poca certezza o in «altro»), {len(dg['weak'])}:")
        for w in dg["weak"][:25]:
            c = w["certainty"]
            print(f"  {w['name']!s:<24} {w['ip']!s:<16} gruppo={w['group']!s:<9} marca={w['brand']!s:<10} certezza n/m/g={c['name']}/{c['brand']}/{c['group']}")
        if len(dg["weak"]) > 25:
            print(f"  … e altri {len(dg['weak']) - 25}")
    if dg["same_name"]:
        print("\nStesso nome su schede diverse:", dg["same_name"])
    h = dg["history"]
    if h:
        print("\nStorico")
        if "presence" in h:
            print(f"  presenza dal {h['presence']['from']} al {h['presence']['to']}")
        if h.get("most_flapping"):
            print("  più eventi di presenza:", ", ".join(f"{i}={n}" for i, n in h["most_flapping"][:5]))
        if h.get("several_macs"):
            print("  schede con più MAC:", ", ".join(f"{i}={n}" for i, n in h["several_macs"]))
        if "scans" in h:
            print(f"  scansioni salvate: {h['scans']['count']} dal {h['scans']['from']} al {h['scans']['to']} · per ora: {h['scans_by_hour']}")
        if "mac_changes_total" in h:
            print(f"  cambi di MAC su una scheda: {h['mac_changes_total']} · MAC noti: {h.get('macs_known')} · schede: " + ", ".join(f"{i}={n}" for i, n, k in h.get("mac_changes", [])[:5]))
    lg = dg.get("log")
    if lg:
        print(f"\nLog: {lg['lines']} righe dal {lg['from']} al {lg['to']} · {lg['levels']}")
        for msg, n in lg["top_problems"]:
            print(f"  {n:>4} × {msg}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("file")
    ap.add_argument("-k", "--key")
    ap.add_argument("--device", help="name, id or last number of the IP of one card")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    try:
        z = load_zip(Path(a.file), Path(a.key) if a.key else None)
    except Exception as exc:
        print(f"Non riesco ad aprire il report: {exc}", file=sys.stderr)
        return 1
    res = card(z, a.device) if a.device else digest(z)
    if a.json:
        print(json.dumps(res, ensure_ascii=False, indent=1, default=str))
    elif a.device:
        print(json.dumps(res, ensure_ascii=False, indent=1, default=str))
    else:
        show(res)
    return 0


if __name__ == "__main__":
    sys.exit(main())
