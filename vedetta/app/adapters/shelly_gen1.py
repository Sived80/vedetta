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
        # Il campo "bat" di /status c'e' solo sui modelli a batteria (H&T, Flood,
        # Door/Window, Motion...): e' una batteria di RETE, il dispositivo e' fisso.
        "battery": "bat" in status,
        "signal_kind": "wifi",
        "signal_value": status.get("wifi_sta", {}).get("rssi"),
        "extra": {
            "model": device.get("type"),
            "firmware": settings.get("fw"),
            "hostname": device.get("hostname"),
        },
    }
