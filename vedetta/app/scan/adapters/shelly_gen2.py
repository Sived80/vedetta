"""Second-generation Shelly devices (RPC API): tells whether the device runs on a battery, from the "devicepower:0" component of Shelly.GetStatus."""
import httpx

from ..scan_common import NO_REQUEST_PORTS


async def battery_probe(ip: str, port: int = 80) -> dict:
    """Second-generation Shelly (RPC API): {"battery": bool, "level": %}. The
    "devicepower:0" component of Shelly.GetStatus exists only on battery
    models (H&T Gen3, Plus sensors...). {} if it does not answer like a Gen2+."""
    if port in NO_REQUEST_PORTS:
        return {}   # never a request to a printing or industrial control port
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
