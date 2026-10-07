import httpx


async def probe(ip: str, port: int = 80) -> dict:
    base = f"http://{ip}:{port}"
    try:
        async with httpx.AsyncClient(timeout=3) as client:
            status = (await client.get(f"{base}/status")).json()
            settings = (await client.get(f"{base}/settings")).json()
    except (httpx.RequestError, ValueError):
        return {"online": False}

    mac_raw = status.get("mac", "")
    mac = ":".join(mac_raw[i:i + 2] for i in range(0, len(mac_raw), 2)) if mac_raw else None

    device = settings.get("device", {})
    return {
        "online": True,
        "name": settings.get("name") or device.get("hostname"),
        "uptime_seconds": status.get("uptime"),
        "mac": mac,
        # The "bat" field of /status only exists on battery-powered models (H&T, Flood,
        # Door/Window, Motion...): it is a NETWORK-device battery, the device itself is fixed.
        "battery": "bat" in status,
        "signal_kind": "wifi",
        "signal_value": status.get("wifi_sta", {}).get("rssi"),
        "extra": {
            "model": device.get("type"),
            "firmware": settings.get("fw"),
            "hostname": device.get("hostname"),
        },
    }
