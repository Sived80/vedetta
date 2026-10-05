"""Brand recognition API: rules created from the interface and
update of the MAC prefix database from the web."""
import asyncio
import logging
import time

from fastapi import APIRouter, HTTPException, Request

from . import brands, i18n, oui_update, vendor_lookup

logger = logging.getLogger("dashboard")
router = APIRouter()

_update_lock = asyncio.Lock()


def _state() -> dict:
    stats = vendor_lookup.oui_stats()
    meta = oui_update.meta()
    updated = meta["updated"] if stats["source"] == "downloaded" else None
    if stats["source"] == "downloaded" and updated is None:
        updated = stats["mtime"]
    age = max(0, int((time.time() - updated) // 86400)) if updated else None
    return {
        "rules": brands.list_rules(),
        "oui": {"blocks": stats["blocks"], "source": stats["source"], "updated": updated, "age_days": age},
        "auto_update": oui_update.auto_update_enabled(),
    }


async def _body(request: Request) -> dict:
    i18n.use_request(request)
    try:
        body = await request.json()
    except ValueError:
        body = None
    if not isinstance(body, dict):
        raise HTTPException(400, i18n.t("brands.error.invalid_body"))
    return body


@router.get("/api/brands")
async def api_brands():
    return await asyncio.to_thread(_state)


@router.post("/api/brands/rules")
async def api_brands_rule_add(request: Request):
    body = await _body(request)
    try:
        await asyncio.to_thread(brands.add_rule, str(body.get("kind", "")), str(body.get("text", "")),
                                str(body.get("brand", "")))
    except ValueError as exc:
        raise HTTPException(400, i18n.t(f"brands.error.invalid_{exc}"))
    except OSError:
        logger.exception("Errore salvando la regola marca")
        raise HTTPException(500, i18n.t("brands.error.save_failed"))
    logger.info("Regola marca aggiunta: %s \"%s\" -> %s", body.get("kind"), str(body.get("text", "")).strip(),
                str(body.get("brand", "")).strip())
    return await asyncio.to_thread(_state)


@router.delete("/api/brands/rules/{rule_id}")
async def api_brands_rule_delete(rule_id: str, request: Request):
    i18n.use_request(request)
    try:
        removed = await asyncio.to_thread(brands.delete_rule, rule_id)
    except OSError:
        logger.exception("Errore eliminando la regola marca %s", rule_id)
        raise HTTPException(500, i18n.t("brands.error.save_failed"))
    if not removed:
        raise HTTPException(404, i18n.t("brands.error.rule_not_found"))
    logger.info("Regola marca eliminata: %s", rule_id)
    return await asyncio.to_thread(_state)


@router.post("/api/brands/preview")
async def api_brands_preview(request: Request):
    try:
        body = await request.json()
    except ValueError:
        body = None
    body = body if isinstance(body, dict) else {}
    mac = str(body.get("mac") or "").strip() or None
    name = str(body.get("name") or "").strip()
    brand = await asyncio.to_thread(vendor_lookup.resolve_brand, mac, None, [name] if name else [])
    return {"brand": brand}


@router.post("/api/brands/update")
async def api_brands_update(request: Request):
    i18n.use_request(request)
    if _update_lock.locked():
        raise HTTPException(409, i18n.t("brands.error.update_running"))
    async with _update_lock:
        try:
            result = await asyncio.to_thread(oui_update.update)
        except oui_update.OuiUpdateError as exc:
            raise HTTPException(502, i18n.t(f"brands.error.update_{exc.code}", detail=exc.detail))
        except Exception:
            logger.exception("Aggiornamento prefissi MAC fallito")
            raise HTTPException(502, i18n.t("brands.error.update_write", detail=""))
    return {"ok": True, "blocks": result["blocks"], "updated": result["updated"]}


@router.post("/api/brands/auto-update")
async def api_brands_auto_update(request: Request):
    body = await _body(request)
    if not isinstance(body.get("enabled"), bool):
        raise HTTPException(400, i18n.t("brands.error.invalid_body"))
    try:
        await asyncio.to_thread(brands.update_user, {"auto_update": body["enabled"]})
    except OSError:
        logger.exception("Errore salvando l'aggiornamento automatico dei prefissi")
        raise HTTPException(500, i18n.t("brands.error.save_failed"))
    logger.info("Aggiornamento automatico prefissi MAC: %s", "attivo" if body["enabled"] else "disattivato")
    return await asyncio.to_thread(_state)
