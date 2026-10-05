"""Status and configuration API for MQTT publishing (GET/POST /api/mqtt).
The password is accepted on write but is never returned."""
from fastapi import APIRouter, HTTPException, Request

from . import settings
from .mqtt_ha import service

router = APIRouter()

# short name in the request body -> settings.json key
_FIELDS = {"enabled": "mqtt_enabled", "host": "mqtt_host", "port": "mqtt_port",
           "user": "mqtt_user", "password": "mqtt_password"}


@router.get("/api/mqtt")
async def api_mqtt_get():
    return service.status()


@router.post("/api/mqtt")
async def api_mqtt_set(request: Request):
    try:
        body = await request.json()
    except ValueError:
        raise HTTPException(400, "JSON non valido")
    if not isinstance(body, dict):
        raise HTTPException(400, "JSON non valido")
    # password absent or null = the saved one is kept; "" = cleared
    changes = {full: body[short] for short, full in _FIELDS.items()
               if short in body and not (short == "password" and body[short] is None)}
    try:
        settings.mqtt_update(changes)
    except ValueError as exc:
        raise HTTPException(400, f"Valore non valido: {exc}")
    except OSError:
        raise HTTPException(500, "Salvataggio non riuscito")
    await service.reconfigure()
    return service.status()
