"""Documented local interfaces of the manufacturers, read-only and without credentials.

A device is queried only if it has the typical port open (seen by the port
scan), with a GET that the manufacturer documents precisely so that it can be recognized:
  Shelly     GET :80/shelly                    -> type/model, mac, fw (gen1 and gen2+)
  Tasmota    GET :80/cm?cmnd=Status%200        -> DeviceName, version, hardware, MAC
  Sonos      GET :1400/xml/device_description.xml (UPnP descriptor)
  Roku       GET :8060/query/device-info        -> vendor-name, model-name, name
  Chromecast GET :8008/setup/eureka_info        -> name, version (if the firmware exposes it)
  ESPHome    GET :80/events (web server, SSE)   -> first "ping" event: device name
Returns api_* fields to use as the declaration of the device itself."""
import asyncio
import json
import re

import httpx

from .discovery import parse_description

_TIMEOUT = 3.0


def parse_shelly(data: dict) -> dict:
    if not isinstance(data, dict) or not (data.get("mac") and (data.get("type") or data.get("model") or data.get("gen"))):
        return {}
    model = data.get("model") or data.get("type")
    return {"api_source": "shelly", "api_vendor": "Shelly", "api_model": model, "api_name": data.get("name"),
            "api_fw": data.get("fw_id") or data.get("fw") or data.get("ver")}


def parse_tasmota(data: dict) -> dict:
    if not isinstance(data, dict) or "StatusFWR" not in data:
        return {}
    st, fwr, net = data.get("Status") or {}, data.get("StatusFWR") or {}, data.get("StatusNET") or {}
    names = st.get("FriendlyName") or []
    return {"api_source": "tasmota", "api_fw": ("Tasmota " + str(fwr.get("Version", ""))).strip(),
            "api_model": fwr.get("Hardware"), "api_name": st.get("DeviceName") or (names[0] if names else None),
            "api_hostname": net.get("Hostname")}


def parse_roku(text: str) -> dict:
    if "<device-info" not in text:
        return {}
    return {"api_source": "roku", "api_vendor": _xml_tag(text, "vendor-name"), "api_model": _xml_tag(text, "model-name"),
            "api_name": _xml_tag(text, "friendly-device-name") or _xml_tag(text, "user-device-name"),
            "api_fw": _xml_tag(text, "software-version")}


def _xml_tag(text: str, tag: str) -> str | None:
    m = re.search(r"<%s>([^<]*)</%s>" % (tag, tag), text)
    return m.group(1).strip() if m and m.group(1).strip() else None


def parse_sonos(text: str) -> dict:
    info = parse_description(text)
    if "sonos" not in (info.get("manufacturer") or "").lower():
        return {}
    return {"api_source": "sonos", "api_vendor": "Sonos", "api_model": info.get("model"), "api_name": info.get("name")}


def parse_esphome_events(text: str) -> dict:
    """First 'ping' event of the ESPHome web server: {"title": name, ...}."""
    for raw in _ping_data_lines(text):
        try:
            data = json.loads(raw)
        except ValueError:
            return {}
        if isinstance(data, dict) and data.get("title"):
            return {"api_source": "esphome", "api_fw": "ESPHome", "api_name": data["title"]}
    return {}


def _ping_data_lines(text: str):
    """The `data:` lines that follow an `event: ping` line (within the next two lines), in the order they appear."""
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if line.strip() == "event: ping":
            yield from (nxt[5:].strip() for nxt in lines[i + 1:i + 3] if nxt.startswith("data:"))


def parse_cast(data: dict) -> dict:
    if not isinstance(data, dict) or not (data.get("name") or data.get("build_version")):
        return {}
    return {"api_source": "cast", "api_name": data.get("name"), "api_fw": data.get("cast_build_revision") or data.get("build_version")}


def plan(ip: str, ports) -> list[tuple[str, str]]:
    """Pure: the (kind, URL) requests worth making for the open ports, in the order in which an answer wins. ESPHome is separate (a stream)."""
    ports = set(ports)
    out: list[tuple[str, str]] = []
    if 80 in ports:
        out += [("shelly", f"http://{ip}/shelly"), ("tasmota", f"http://{ip}/cm?cmnd=Status%200")]
    if 1400 in ports:
        out.append(("sonos", f"http://{ip}:1400/xml/device_description.xml"))
    if 8060 in ports:
        out.append(("roku", f"http://{ip}:8060/query/device-info"))
    if 8008 in ports:
        out.append(("cast", f"http://{ip}:8008/setup/eureka_info"))
    return out


def interpret(kind: str, text: str) -> dict:
    """Pure: what the answer of one interface says about the device ({} if it is not the expected shape)."""
    try:
        if kind in ("shelly", "tasmota", "cast"):
            return {"shelly": parse_shelly, "tasmota": parse_tasmota, "cast": parse_cast}[kind](json.loads(text))
        return {"sonos": parse_sonos, "roku": parse_roku}[kind](text)
    except ValueError:
        return {}


async def probe(ip: str, ports, transport=None) -> dict:
    """Tries only the interfaces of the open ports; the first one that answers
    with the expected shape wins. {} if none. `transport` lets a test replace the network (httpx.MockTransport)."""
    ports = set(ports)
    requests = plan(ip, ports)
    if not requests:
        return {}
    async with httpx.AsyncClient(timeout=_TIMEOUT, follow_redirects=False, transport=transport) as client:
        jobs = [(kind, _get(client, url)) for kind, url in requests]
        if 80 in ports:
            jobs.append(("esphome", asyncio.wait_for(_esphome(client, ip), _TIMEOUT)))
        results = await asyncio.gather(*(j for _, j in jobs), return_exceptions=True)
    return _first_answer([kind for kind, _ in jobs], results)


async def _esphome(client: httpx.AsyncClient, ip: str) -> dict:
    """Reads only the beginning of the /events stream (which otherwise stays open)."""
    try:
        async with client.stream("GET", f"http://{ip}/events") as resp:
            if resp.status_code != 200 or "event-stream" not in resp.headers.get("content-type", ""):
                return {}
            return await _first_ping(resp)
    except Exception:
        return {}


async def _first_ping(resp) -> dict:
    """What the stream says about the device, as soon as it says it (or {} when the stream ends or 4 KiB went by with nothing)."""
    buf = ""
    async for chunk in resp.aiter_text():
        buf += chunk
        found = parse_esphome_events(buf)
        if found or len(buf) > 4096:
            return found
    return {}


async def _get(client: httpx.AsyncClient, url: str):
    try:
        resp = await client.get(url)
    except Exception:
        return None
    if resp.status_code != 200:
        return None
    return resp


def _first_answer(kinds: list[str], results: list) -> dict:
    """The first request, in the order of the plan, whose answer has the expected shape (empty fields dropped, except for the ESPHome stream); {} if none."""
    for kind, resp in zip(kinds, results):
        found = _answer_of(kind, resp)
        if found:
            return {k: v for k, v in found.items() if v} if kind != "esphome" else found
    return {}


def _answer_of(kind: str, resp) -> dict:
    """What one finished request says about the device: {} if it failed (no answer, an exception) or if the answer is not of the expected shape."""
    if resp is None or isinstance(resp, Exception):
        return {}
    return resp if kind == "esphome" else interpret(kind, resp.text)
