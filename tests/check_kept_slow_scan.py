"""What the search learned about a device is kept when the device is added; this includes «the device is slow»: a deep search started a minute later must not
run the 1000-port pilot again (14-16 s on a small device, close to the host timeout). Found in a real export: every Shelly was piloted twice in two minutes."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app.routes import device_routes  # noqa: E402

kept = device_routes._kept_scan_info
assert kept({"http_title": "Shelly Web Admin", "slow_scan": True}) == {"http_title": "Shelly Web Admin", "slow_scan": True}
assert kept({"http_title": "x", "slow_scan": False}) == {"http_title": "x"}      # not slow: nothing to remember
assert kept({"slow_scan": True}) == {"slow_scan": True}                           # and it stays a real boolean, not a text
assert kept({"http_title": "t" * 500})["http_title"] == "t" * 200                 # the short-text rule of the other keys is unchanged
assert kept(None) == {} and kept("x") == {} and kept({}) == {}
# The ports the search saw are kept too (a deep search that comes back empty, or never comes, must not leave a new card with none): only what the
# search itself writes is taken from the page, cleaned; a bad entry is dropped, never an error.
ports = [{"label": "554 · rtsp", "confirmed": True, "category": "media"}, {"label": "80 · Boa httpd", "confirmed": True, "category": "web", "web_ui": True, "web_scheme": "http"}]
assert kept({"ports": ports})["ports"] == ports
assert kept({"ports": [{"label": "22", "category": "<script>", "web_scheme": "x", "web_ui": 1, "extra": "x"}]})["ports"] == [{"label": "22", "confirmed": False, "category": "other", "web_ui": True, "web_scheme": "http"}]
assert kept({"ports": [{"label": "nothing"}, {"confirmed": True}, "text", None, 5]}) == {}                   # no port number: dropped
assert kept({"ports": "80"}) == {} and kept({"ports": []}) == {} and kept({"ports": {"a": 1}}) == {}
assert len(kept({"ports": [{"label": str(n)} for n in range(1, 500)]})["ports"]) == 100                     # a bounded list
assert len(kept({"ports": [{"label": "8" * 300}]})["ports"][0]["label"]) == 80
assert "scanned_at" not in kept({"ports": ports, "scanned_at": 1.0})                                         # «ports and services really read» stays for the deep search
print("TUTTO OK")
