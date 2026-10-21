"""Port alerts and the churn of the high ports (scan/rescan.py diff_ports): a device that keeps its listening ports in the default dynamic range of Linux (32768 and up: a TV, a phone, a repeater)
opens some and closes others at every deep search, so "new port 33297" and "port closed 34729" are noise. When the high band changes in BOTH directions in one comparison it is churn and raises nothing;
a change in one direction only (a service that appears or goes), and every change below the band, still raises. The numbers below are the real sequences seen on a home network (no name, no address)."""
import os
import sys
import tempfile

os.environ["VEDETTA_DATA_DIR"] = tempfile.mkdtemp()
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app.scan import rescan  # noqa: E402


def ports(*numbers):
    return [{"label": str(n)} for n in numbers]


def diff(old, new):
    return rescan.diff_ports(ports(*old), ports(*new))


# --- the band: 32768 is the start of the default range of Linux, 32767 is not
assert rescan.CHURN_BAND_START == 32768
assert diff([], [32767]) == ([32767], []) and diff([32767], []) == ([], [32767]), "below the band: always raised"

# --- churn: both directions in the band, nothing is raised (the real sequences of a TV, a phone and a repeater)
assert diff([34729, 37889, 40841, 46857], [33297, 36075, 39173]) == ([], [])
assert diff([34491, 41881, 43839], [37615, 42024, 45242]) == ([], [])
assert diff([33481], [46623]) == ([], [])
assert diff([80, 34729, 37889], [80, 33297]) == ([], []), "the stable port is unchanged and the churn is silent"

# --- the edge of the band: 32768 is inside (it counts for the churn and is silenced with it), 32767 is outside (it is a port like any other)
assert diff([32768], [33000]) == ([], []), "32768 closes while 33000 opens: churn"
assert diff([32767], [33000]) == ([33000], [32767]), "32767 is not in the band: 33000 appears alone in the band, so nothing is churn"
assert diff([33000], [32768]) == ([], []), "churn the other way round"

# --- one direction only: a service that appears alone or goes alone still raises
assert diff([80], [80, 40000]) == ([40000], [])
assert diff([80, 40000], [80]) == ([], [40000])

# --- below the band nothing is hidden, even in the middle of churn
assert diff([34729, 37889, 22], [33297, 36075, 8883]) == ([8883], [22])
assert diff([23478, 34939, 36003], [33297]) == ([], [23478]), "a port below the band that closes is raised; the high ones are the churn"

# --- ports from 49152 up are still never raised (the older rule), but they count for the churn: a port that closes while one of them opens is churn
assert diff([34729], [50000]) == ([], []), "34729 closes, 50000 opens: both directions in the high band"
assert diff([34729], []) == ([], [34729]), "a high port that goes alone is raised"
assert diff([], [50000]) == ([], []), "a port from 49152 up that appears alone is never raised (older rule)"

# --- the old behaviour on the plain cases
assert diff([22, 80], [80, 8883]) == ([8883], [22])
assert rescan.diff_ports(None, ports(80, 8883)) == ([80, 8883], [])
print("check_port_churn OK")
