"""Contract test of scan/localapi.py: the requests made for each set of open ports (pure plan), the reading of each manufacturer's answer (pure
interpretation), and the whole probe against a fake HTTP server in memory (httpx.MockTransport) that answers like the documented interfaces do.
The samples are written from the manufacturers' public documentation, not recorded from a device: replace them with real captures when available."""
import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
import httpx  # noqa: E402
from app.scan import localapi as la  # noqa: E402

SHELLY = '{"type": "SHSW-1", "mac": "AABBCC001122", "fw": "20230913-114008/v1.14.0", "name": "Boiler"}'
SHELLY2 = '{"model": "SNSW-001X16EU", "mac": "AABBCC001122", "gen": 2, "fw_id": "20240101-000000/1.2.3", "name": "Gen2 relay"}'
TASMOTA = ('{"Status": {"DeviceName": "Presa", "FriendlyName": ["Presa"]}, "StatusFWR": {"Version": "13.1.0", "Hardware": "ESP8266EX"},'
           ' "StatusNET": {"Hostname": "tasmota-1"}}')
ROKU = "<device-info><vendor-name>Roku</vendor-name><model-name>Express</model-name><friendly-device-name>Salotto</friendly-device-name><software-version>12.5</software-version></device-info>"
SONOS = ('<root><device><manufacturer>Sonos, Inc.</manufacturer><modelName>Sonos One</modelName><friendlyName>Cucina - Sonos One</friendlyName>'
         '</device></root>')
CAST = '{"name": "Living room TV", "build_version": "12345", "cast_build_revision": "1.56.500000"}'
ESPHOME = "retry: 30000\n\nevent: ping\ndata: {\"title\": \"garage-door\", \"comment\": \"\"}\n\n"

# --- the plan: only the interfaces of the open ports, in the order in which an answer wins
assert la.plan("10.0.0.5", [22, 443]) == [] and la.plan("10.0.0.5", []) == []
assert [k for k, _ in la.plan("10.0.0.5", [80, 1400, 8060, 8008])] == ["shelly", "tasmota", "sonos", "roku", "cast"]
assert la.plan("10.0.0.5", [8060]) == [("roku", "http://10.0.0.5:8060/query/device-info")]
assert la.plan("10.0.0.5", {80})[1] == ("tasmota", "http://10.0.0.5/cm?cmnd=Status%200")

# --- the interpretation
assert la.interpret("shelly", SHELLY)["api_model"] == "SHSW-1" and la.interpret("shelly", SHELLY2)["api_model"] == "SNSW-001X16EU"
assert la.interpret("tasmota", TASMOTA) == {"api_source": "tasmota", "api_fw": "Tasmota 13.1.0", "api_model": "ESP8266EX", "api_name": "Presa", "api_hostname": "tasmota-1"}
assert la.interpret("roku", ROKU)["api_name"] == "Salotto" and la.interpret("sonos", SONOS)["api_vendor"] == "Sonos"
assert la.interpret("cast", CAST)["api_name"] == "Living room TV"
assert la.interpret("shelly", "not json") == {} and la.interpret("shelly", "[]") == {} and la.interpret("sonos", "<root/>") == {}
assert la.interpret("shelly", TASMOTA) == {}, "a Tasmota answer is not a Shelly"
assert la.parse_esphome_events(ESPHOME)["api_name"] == "garage-door" and la.parse_esphome_events("event: ping\ndata: {bad") == {}


def server(routes, seen):
    """A fake device: path (and query) -> (status, content-type, body); anything else 404."""
    def handler(request: httpx.Request) -> httpx.Response:
        key = request.url.raw_path.decode()
        seen.append(f"{request.url.host}:{request.url.port or 80}{key}")
        if key in routes and routes[key] == "boom":
            raise httpx.ConnectError("refused")
        status, ctype, body = routes.get(key, (404, "text/plain", "not found"))
        return httpx.Response(status, headers={"content-type": ctype}, text=body)
    return httpx.MockTransport(handler)


def probe(ports, routes, ip="10.0.0.5"):
    seen = []
    out = asyncio.run(la.probe(ip, ports, transport=server(routes, seen)))
    return out, seen


J, X = "application/json", "text/xml"
out, seen = probe([22, 443], {})
assert out == {} and seen == [], "no interesting port: not a single request"
out, seen = probe([80], {"/shelly": (200, J, SHELLY)})
assert out["api_source"] == "shelly" and out["api_vendor"] == "Shelly" and out["api_model"] == "SHSW-1" and "10.0.0.5:80/shelly" in seen
out, _ = probe([80], {"/shelly": (404, "text/plain", ""), "/cm?cmnd=Status%200": (200, J, TASMOTA)})
assert out["api_source"] == "tasmota" and out["api_name"] == "Presa"
out, _ = probe([80], {"/events": (200, "text/event-stream", ESPHOME)})
assert out == {"api_source": "esphome", "api_fw": "ESPHome", "api_name": "garage-door"}
out, _ = probe([80], {"/events": (200, "text/html", ESPHOME)})
assert out == {}, "an /events page that is not an event stream is ignored"
out, _ = probe([1400], {"/xml/device_description.xml": (200, X, SONOS)})
assert out["api_source"] == "sonos" and out["api_model"] == "Sonos One"
out, _ = probe([8060], {"/query/device-info": (200, X, ROKU)})
assert out["api_source"] == "roku" and out["api_fw"] == "12.5"
out, _ = probe([8008], {"/setup/eureka_info": (200, J, CAST)})
assert out["api_source"] == "cast" and out["api_name"] == "Living room TV"
out, _ = probe([80], {"/shelly": (200, J, SHELLY), "/cm?cmnd=Status%200": (200, J, TASMOTA)})
assert out["api_source"] == "shelly", "when two answer, the first in the plan wins"
out, _ = probe([80], {"/shelly": "boom", "/cm?cmnd=Status%200": (500, J, TASMOTA)})
assert out == {}, "a refused connection and an error status are survived"
out, _ = probe([80], {"/shelly": (200, J, "{broken")})
assert out == {}, "a broken body is survived"
out, _ = probe([80, 8008], {"/shelly": (200, J, '{"type": "SHSW-1", "mac": "AA", "name": null}')})
assert "api_name" not in out and out["api_model"] == "SHSW-1", "empty fields are dropped"
print("TUTTO OK")
