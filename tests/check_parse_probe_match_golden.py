"""Golden-master test of discovery.parse_probe_match (WS-Discovery ProbeMatch -> fields): 4000 generated packets - valid and malformed XML, documents with and without a ProbeMatch
element, repeated and empty Types / Scopes / XAddrs elements, ONVIF scopes in every spelling (case, "mfr", percent escapes, underscores, repeated keys, empty values), non-ONVIF scopes,
types with and without a prefix - must give exactly the results stored in tests/golden/parse_probe_match.json, written from the code as it was before the function was split
(the key order of the returned dictionaries counts).
Regenerate only on purpose:  PROBEMATCH_GOLDEN_UPDATE=1 python tests/check_parse_probe_match_golden.py"""
import json
import os
import random
import sys
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app.scan import discovery  # noqa: E402

GOLDEN = Path(__file__).parent / "golden" / "parse_probe_match.json"
N = 4000
rng = random.Random(1357911)

TYPES = ["dn:NetworkVideoTransmitter tds:Device", "wsdp:Printer", "", "  ", "NetworkVideoTransmitter", "a:b:c", " dn:NetworkVideoTransmitter ", "tds:Device", "x:networkvideotransmitter",
         "wsdp:Device pub:Computer"]
BASE = "onvif://www.onvif.org/"
SCOPES = [BASE + "name/IPCAM", BASE + "name/My%20Cam_1", BASE + "hardware/C6F0SgZ3N0PdL2", BASE + "manufacturer/Acme", BASE + "mfr/Foo_Bar", BASE + "MFR/UPPER",
          BASE + "model/M1", BASE + "location/city/rome", BASE + "type/video_encoder", BASE + "Name/CASE", BASE + "name/", BASE + "other/x", "http://x/name/y",
          "ONVIF://WWW.ONVIF.ORG/name/up", BASE + "name/%20_%20", BASE + "name/%41%42", BASE + "hardware/", BASE + "model/%20", BASE + "location/_", BASE + "manufacturer/ _x_ ",
          "onvif://www.onvif.org/Profile/Streaming", "urn:something", "x" + BASE + "name/A", BASE + "name/A extra"]
XADDRS = ["", "http://192.168.1.5:80/onvif/device_service", "http://192.168.1.5/a http://[fe80::1]/b", "  http://h/x  ", "\n http://h/y \n http://h/z"]
NS = ' xmlns:d="http://schemas.xmlsoap.org/ws/2005/04/discovery" xmlns:w="http://x/w"'


def pick(seq):
    return seq[rng.randrange(len(seq))]


def elem(name, text):
    tag = pick(["d:" + name, name, "w:" + name]) if rng.random() < 0.8 else name
    if tag.startswith("w:") or tag.startswith("d:"):
        return "<%s>%s</%s>" % (tag, text, tag)
    return "<%s>%s</%s>" % (tag, text, tag)


def field_elems():
    parts = []
    for name, pool in (("Types", TYPES), ("Scopes", None), ("XAddrs", XADDRS)):
        for _ in range(pick([0, 1, 1, 1, 2, 3])):
            if pool is None:
                text = " ".join(pick(SCOPES) for _ in range(rng.randrange(0, 6)))
                if rng.random() < 0.15:
                    text = ""
            else:
                text = pick(pool)
            if rng.random() < 0.05:
                parts.append("<d:%s/>" % name)
            else:
                parts.append(elem(name, text))
    rng.shuffle(parts)
    return "".join(parts)


def packet():
    r = rng.random()
    if r < 0.04:
        return pick([b"", b"<a><b></a>", b"not xml", b"<?xml version='1.0'?>", b"<a>", None, 5, "<d:ProbeMatch/>"])
    fields = field_elems()
    style = rng.random()
    if style < 0.6:
        body = "<d:ProbeMatches><d:ProbeMatch>%s</d:ProbeMatch></d:ProbeMatches>" % fields
    elif style < 0.7:
        body = "<d:ProbeMatches><d:ProbeMatch/>%s</d:ProbeMatches>" % fields
    elif style < 0.8:
        body = "<d:ProbeMatches>%s<ProbeMatch/></d:ProbeMatches>" % fields
    else:
        body = "<d:ProbeMatches>%s</d:ProbeMatches>" % fields  # no ProbeMatch element at all
    return ('<e:Envelope xmlns:e="http://e"%s><e:Body>%s</e:Body></e:Envelope>' % (NS, body)).encode()


out = []
stats = {"none": 0, "ok": 0, "onvif": 0, "onvif_types_only": 0, "name": 0, "hardware": 0, "manufacturer": 0, "model": 0, "location": 0, "exc": 0}
for _ in range(N):
    data = packet()
    try:
        r = discovery.parse_probe_match(data)
        out.append(r)
        if r is None:
            stats["none"] += 1
        else:
            stats["ok"] += 1
            stats["onvif"] += bool(r["onvif"])
            stats["onvif_types_only"] += bool(r["onvif"]) and not any(k in r for k in ("name", "hardware", "manufacturer", "model", "location"))
            for k in ("name", "hardware", "manufacturer", "model", "location"):
                stats[k] += k in r
    except Exception as exc:
        out.append({"exception": type(exc).__name__})
        stats["exc"] += 1

text_out = json.dumps(out)  # no sort_keys: the key order counts
if os.environ.get("PROBEMATCH_GOLDEN_UPDATE") or not GOLDEN.exists():
    GOLDEN.parent.mkdir(exist_ok=True)
    GOLDEN.write_text(text_out, encoding="utf-8")
    print("golden written")
want = json.loads(GOLDEN.read_text(encoding="utf-8"))
assert len(want) == len(out) == N
for i, (x, y) in enumerate(zip(out, want)):
    assert json.dumps(x) == json.dumps(y), "case %d differs: %s" % (i, json.dumps([x, y])[:600])
assert text_out == GOLDEN.read_text(encoding="utf-8"), "key order or formatting differs"
assert stats["none"] > 300 and stats["ok"] > 2000 and stats["onvif"] > 800 and stats["onvif_types_only"] > 50, "too uniform: %s" % stats
assert all(stats[k] > 150 for k in ("name", "hardware", "manufacturer", "model", "location")), "too uniform: %s" % stats
assert 0 < stats["exc"] < 100, stats
print("TUTTO OK")
