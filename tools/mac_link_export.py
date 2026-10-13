"""Runs the MAC identity linker (app/macidentity.py) and the classifier on a real export that has the ip_mac table (0.6.2-debug and later).
  python tools/mac_link_export.py [ZIP]     default: the newest vedetta-analisi-*.zip in ~/.vedetta/exports
Private data (the output is for the developer's eyes only; MACs are shortened)."""
import json
import sqlite3
import sys
import tempfile
import zipfile
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "vedetta"))
from app import maclayer, macclassify, macidentity  # noqa: E402


def short(m):
    return m[:8] + ".." + m[-2:]


def load(zpath):
    zf = zipfile.ZipFile(zpath)
    tmp = Path(tempfile.mkdtemp()) / "v.db"
    tmp.write_bytes(zf.read("data/vedetta.db"))
    db = sqlite3.connect(tmp)
    rows = [dict(zip(("ip", "mac", "source", "first_seen", "last_seen", "seen_count"), r))
            for r in db.execute("SELECT ip, mac, source, first_seen, last_seen, seen_count FROM ip_mac")]
    try:
        sessions = [dict(zip(("ip", "mac", "source", "start", "end"), r)) for r in db.execute("SELECT ip, mac, source, start, end FROM ip_mac_session")]
    except sqlite3.OperationalError:
        sessions = []                                   # an export from before the sessions existed
    dhcp = {k.upper(): v for k, v in json.loads(zf.read("data/dhcp_seen.json")).items()}
    return rows, dhcp, sessions


def features(rows, dhcp, sessions=()):
    return maclayer.features_for_linking(rows, list(sessions), dhcp)


def _features_old(rows, dhcp, sessions=()):
    feats = defaultdict(lambda: {"first": 1e18, "last": 0.0, "ips": set()})
    for r in rows:
        if r["source"] == "mdns":
            continue                                    # a name heard, not activity of the MAC
        f = feats[r["mac"]]
        f["first"], f["last"] = min(f["first"], r["first_seen"]), max(f["last"], r["last_seen"])
        f["ips"].add(r["ip"])
    by_mac = defaultdict(list)
    for s in sessions:
        if s["source"] != "mdns":
            by_mac[s["mac"]].append((s["start"], s["end"], (s["ip"],)))
    for mac, f in feats.items():
        if by_mac.get(mac):
            f["sessions"] = by_mac[mac]
        d = dhcp.get(mac) or {}
        if d.get("hostname"):
            f["hostname"] = d["hostname"]
        if d.get("vendor_class") or d.get("prl"):
            f["fingerprint"] = f"{d.get('vendor_class', '')}|{d.get('prl', '')}"
    return dict(feats)


if __name__ == "__main__":
    z = sys.argv[1] if len(sys.argv) > 1 else str(sorted((Path.home() / ".vedetta" / "exports").glob("vedetta-analisi-*.zip"))[-1])
    rows, dhcp, sessions = load(z)
    feats = features(rows, dhcp, sessions)
    res = macclassify.classify(rows)
    print(f"{Path(z).name}: {len(rows)} righe ip_mac, {len(feats)} MAC, {len(dhcp)} client DHCP")
    print("tipi:", {k: sum(1 for v in res['macs'].values() if v['kind'] == k) for k in sorted({v['kind'] for v in res['macs'].values()})})
    for mac, v in res["macs"].items():
        if v["kind"] not in ("normal", "private"):
            print(f"  {v['kind']:13s} {short(mac)} su {len(v['ips'])} IP: {', '.join(i.rsplit('.', 1)[-1] for i in v['ips'])}")
    pairs = macidentity.link(feats)
    print("coppie di MAC (le migliori):")
    for p in pairs[:6]:
        print(f"  {p['zone']:9s} {p['score']:+6.1f}  {short(p['a'])} - {short(p['b'])}: {'; '.join(p['why']) or 'nessuna prova'}")
    from collections import Counter
    print("zone su tutte le coppie:", dict(Counter(p["zone"] for p in pairs)))
