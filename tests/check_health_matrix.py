"""The matrix of the network-health rules (health/matrix.py): the file that ships is valid, and every way a row can be wrong is refused with the id of the row and the name of the field."""
import copy
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app.health import detectors, matrix  # noqa: E402

GOOD = {"id": "H99", "family": "conflict", "params": {"min_cycles": 2, "clear_cycles": 3}, "signals": ["ARP"], "scope": "live", "class": "configuration", "severity": "warning",
        "message_key": "health.h99", "remedy_key": "health.h99.remedy", "detectability": "D1", "status": "shadow", "since": "next",
        "existence": {"grade": "A", "sources": [{"title": "IPv4 Address Conflict Detection", "link": "https://www.rfc-editor.org/rfc/rfc5227", "verified": True}]}}


def refused(change, field):
    row = copy.deepcopy(GOOD)
    change(row)
    try:
        matrix.validate([row])
    except ValueError as exc:
        assert "H99" in str(exc) and field in str(exc), "the error must name the row and the field: %s" % exc
        return
    raise AssertionError("a row with a bad %s was accepted" % field)


matrix.validate([GOOD])

rows = matrix.load()
assert rows, "the shipped matrix is empty"
assert all(r["family"] in detectors.FAMILIES for r in rows), "a row uses a family that has no detector"
assert all(r["status"] in ("draft", "shadow", "active") for r in rows)

refused(lambda r: r.pop("severity"), "severity")
refused(lambda r: r.update(severity="catastrophic"), "severity")
refused(lambda r: r.update(family="telepathy"), "family")
refused(lambda r: r.update(status="visible"), "status")
refused(lambda r: r.update(detectability="D9"), "detectability")
refused(lambda r: r["existence"].update(grade="Z"), "existence")
refused(lambda r: r["existence"]["sources"][0].update(link="ftp://x"), "link")
refused(lambda r: r["params"].update(min_cycles=0), "min_cycles")
refused(lambda r: r.update(signals="ARP"), "signals")

try:
    matrix.validate([GOOD, copy.deepcopy(GOOD)])
    raise AssertionError("two rows with the same id were accepted")
except ValueError as exc:
    assert "H99" in str(exc) and "twice" in str(exc), exc

print("check_health_matrix OK")
