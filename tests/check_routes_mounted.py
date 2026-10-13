"""The real application mounts every router once: no route (method and path) appears twice, and the groups of routes that live in their own modules are all there (the export was moved out of routes/ha.py:
a router that is written but not included in main.py would only show up in the page, as a 404)."""
import collections
import os
import sys
import tempfile

os.environ["VEDETTA_DATA_DIR"] = tempfile.mkdtemp()
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app import main  # noqa: E402

routes = [(method, route.path) for route in main.app.routes for method in sorted(getattr(route, "methods", None) or [])]
twice = [key for key, count in collections.Counter(routes).items() if count > 1]
assert not twice, "a route is mounted twice: %s" % twice

EXPECTED = {
    ("POST", "/api/export"), ("GET", "/api/export/info"), ("POST", "/api/export/jobs"), ("GET", "/api/export/jobs/{job_id}"), ("DELETE", "/api/export/jobs/{job_id}"),
    ("POST", "/api/export/jobs/{job_id}/choices"), ("POST", "/api/export/jobs/{job_id}/file"),
    ("GET", "/ha"), ("GET", "/api/ha/devices"), ("GET", "/api/ha/events"), ("GET", "/api/ha/summary"),
    ("POST", "/api/settings"), ("POST", "/api/pause"),
}
missing = sorted(EXPECTED - set(routes))
assert not missing, "a route is not mounted: %s" % missing
print("TUTTO OK", len(routes), "routes")
