"""The "open web interface" button only appears where a real page answers (not a 404, not an API port)."""
import asyncio
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app import i18n
from app.scan import probe, scanner  # noqa: E402

i18n.use("en")

# --- pure rule
assert scanner.is_web_ui(200, "Router", 500) and scanner.is_web_ui(200, None, 2000)
assert scanner.is_web_ui(302, None, 0) and scanner.is_web_ui(401, None, 0)
assert not scanner.is_web_ui(404, "404 Not Found", 146)      # nginx error page of a TV
assert not scanner.is_web_ui(400, None, 0)                   # control port of a streaming stick
assert not scanner.is_web_ui(500, "Error", 300) and not scanner.is_web_ui(None, None, 0)
assert not scanner.is_web_ui(200, None, 19)                  # a few bytes of API output


# --- against real local servers
class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        route = {"/": None}
        code, body = {18101: (404, b"<html><title>404 Not Found</title><center>nginx</center></html>" * 2),
                      18102: (200, b"<html><title>My router</title><body>login</body></html>"),
                      18103: (401, b""), 18104: (200, b"ok")}[self.server.server_port]
        self.send_response(code)
        self.send_header("Content-Type", "text/html")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


servers = []
for port in (18101, 18102, 18103, 18104):
    srv = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    servers.append(srv)

ports = [{"port": p, "service": "http", "confirmed": True} for p in (18101, 18102, 18103, 18104)]
asyncio.run(scanner._confirm_http_ports("127.0.0.1", ports))
by_port = {p["port"]: p for p in ports}
assert by_port[18101]["web_ui"] is False, by_port[18101]     # 404 page: not an interface
assert by_port[18102]["web_ui"] is True                      # real page with a title
assert by_port[18103]["web_ui"] is True                      # login required
assert by_port[18104]["web_ui"] is False                     # "ok" is API output
for s in servers:
    s.shutdown()

# --- the saved ports keep the verdict, and the device card uses it
fields = scanner.format_scan_info({"ports": [{"port": 18101, "service": "http", "confirmed": True, "web_ui": False},
                                             {"port": 18102, "service": "http", "confirmed": True, "web_ui": True,
                                              "web_scheme": "https"}]})
saved = fields["ports"]
assert saved[0]["web_ui"] is False and saved[1]["web_ui"] is True and saved[1]["web_scheme"] == "https"
for p, n in zip(saved, (18101, 18102)):
    p["label"] = f"{n} · http"

assert probe._web_open(saved) is True
assert probe._web_open([{"label": "80 · http", "web_ui": False}]) is False
assert probe._web_open([{"label": "80 · http"}]) is None                       # never checked: old rule applies
# the button points to the real page, with https where needed, even if the device was added with another port
assert probe._web_url("10.0.0.3", 18101, saved) == "https://10.0.0.3:18102"
assert probe._web_url("10.0.0.3", 18102, saved) == "https://10.0.0.3:18102"
assert probe._web_url("10.0.0.3", 8009, [{"label": "8009 · x", "web_ui": False}]) == "http://10.0.0.3:8009"
assert probe._web_url("10.0.0.3", 80, [{"label": "8080 · http", "web_ui": True, "web_scheme": "http"},
                                       {"label": "80 · http", "web_ui": True, "web_scheme": "http"}]) == "http://10.0.0.3:80"
# a 403 is a refusal, not a login (the UPnP port 1400 of a Sonos answers 403 and was offered as "open web interface")
assert not scanner.is_web_ui(403, None, 10) and not scanner.is_web_ui(403, "Camera login", 900)   # a refusal is not a page for people
# the default port is closed but another port is a web service (Glances on 61208): the button points there; if the port is open it stays
glances = [{"label": "22 · OpenSSH", "category": "remote", "confirmed": True}, {"label": "61208 · WSGIServer", "category": "web", "confirmed": True}]
assert probe._web_url("10.0.0.2", 80, glances) == "http://10.0.0.2:61208"
assert probe._web_url("10.0.0.2", 61208, glances) == "http://10.0.0.2:61208"
assert probe._web_url("10.0.0.2", 80, []) == "http://10.0.0.2:80"                                      # nothing known: unchanged
assert probe._web_url("10.0.0.2", 80, [{"label": "22 · OpenSSH", "category": "remote", "confirmed": True}]) == "http://10.0.0.2:80"
print("TUTTO OK")
