"""Issue #57: the export for the developer stayed on step 2 ("Masking IPs, MACs, names and emails"). The masking time must grow with the
size of the text, not with size x number of names, and no single token may cost quadratic time:
  - the names are one alternation; with the word-edge guard written inside every branch the engine tried every name at every character
    (300 names: about 5 s per MB on a desktop, minutes on a small Home Assistant box, for logs, database and snapshots together);
  - the e-mail pattern could start at every character of a long run of letters, digits, dots or dashes: quadratic in the run.
The results must not change: same spans as the old way of writing the names. Invented names and addresses only."""
import os
import re
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app.export import anonymize  # noqa: E402
from app.export.anonymize_patterns import _pattern  # noqa: E402

NAMES = [f"Kitchen Shelf Lamp {i:03d}" if i % 2 else f"Gartenhaus-Sensor-{i:03d}" for i in range(300)]


def build(names):
    a = anonymize.Anonymizer()
    a.add_ip("192.168.77.1")
    a.add_devices([([n], None, None, None) for n in names])
    return a


def log(names, lines=6000):
    return "\n".join(f"2026-11-20 10:00:{i % 60:02d} INFO probe 192.168.77.{i % 250} name={names[i % len(names)]} answered in 12 ms state=online" for i in range(lines))


def timed(fn, *args):
    t = time.perf_counter()
    out = fn(*args)
    return out, time.perf_counter() - t


# 1. names: the cost of 300 names against the cost of 2 (same text length): a few times more, never ~100 times
many = build(NAMES)
few = build(NAMES[:2])
text = log(NAMES)
_, t_few = timed(few.text, text)
masked, t_many = timed(many.text, text)
print(f"{len(text) / 1e6:.2f} MB: 2 names {t_few:.2f}s, 300 names {t_many:.2f}s")
assert t_many < max(4 * t_few, 0.5), ("masking time grows with the number of names", t_few, t_many)
assert not any(n.lower() in masked.lower() for n in NAMES), "a name is still readable"

# same matches as the old alternation (the guard inside every branch)
table = {**many._areas, **many._names}
old = re.compile("|".join(_pattern(k.replace("-", " ")) for k in sorted(table, key=len, reverse=True)), re.IGNORECASE | re.UNICODE)
probe = text[:200000] + " gartenhaus_sensor_002 xKitchen Shelf Lamp 001 Kitchen-Shelf-Lamp-001y Kitchen  Shelf_Lamp 003."
assert [m.span() for m in many._compile().finditer(probe)] == [m.span() for m in old.finditer(probe)]

# 2. one long token without "@" (a hex dump, a long id): linear, not quadratic
_, t_tok = timed(anonymize.Anonymizer().text, "a1b2c3d4e5" * 6000)
print(f"60 kB token: {t_tok:.2f}s")
assert t_tok < 1.0, ("quadratic e-mail scan", t_tok)
a = anonymize.Anonymizer()
assert a.text("x" * 5000 + ".joe@example.net y") == "x" * (5000 + 4 - 64) + "email-1@masked.invalid y"   # an address is at most 64 characters before "@"
assert a.text("mail a@b@mail.example.org") == "mail a@email-2@masked.invalid"
assert a.text("bob@example.org+c@home.example.net") == "email-3@masked.invalidemail-4@masked.invalid"   # two in one run: both masked

print("OK anonymizer speed")
