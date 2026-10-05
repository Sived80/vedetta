import httpx


async def battery_probe(ip: str, port: int = 80) -> dict:
    """Shelly di seconda generazione (API RPC): {"battery": bool, "level": %}. Il
    componente "devicepower:0" di Shelly.GetStatus esiste solo sui modelli a
    batteria (H&T Gen3, sensori Plus...). {} se non risponde come un Gen2+."""
    try:
        async with httpx.AsyncClient(timeout=3) as client:
            status = (await client.get(f"http://{ip}:{port}/rpc/Shelly.GetStatus")).json()
    except (httpx.RequestError, ValueError):
        return {}
    if not isinstance(status, dict) or "sys" not in status:
        return {}
    power = next((v for k, v in status.items() if k.startswith("devicepower") and isinstance(v, dict)), None)
    level = (power or {}).get("battery", {}).get("percent") if power else None
    return {"battery": power is not None, "level": level}
