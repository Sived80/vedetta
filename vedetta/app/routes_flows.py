"""API of the search flows: which functions (steps) each profile enables."""
from fastapi import APIRouter, HTTPException, Request

from . import flows, i18n, settings
from .applog import logger

router = APIRouter()


def _payload() -> dict:
    """Registry, active flows and defaults, with texts in the request's language."""
    active = settings.flows_load()
    return {
        "steps": [
            {
                "id": s.id,
                "label": i18n.t(f"flow.step.{s.id}.label"),
                "description": i18n.t(f"flow.step.{s.id}.description"),
                "flows": list(s.flows),
                "locked_in": list(s.locked_in),
                "risk": s.risk,
            }
            for s in flows.STEPS
        ],
        "flows": {
            p: {
                "label": i18n.t(f"flow.profile.{p}.label"),
                "description": i18n.t(f"flow.profile.{p}.description"),
                "steps": active[p],
            }
            for p in flows.PROFILES
        },
        "risks": {k: {"label": i18n.t(f"flow.risk.{k}.label"), "description": i18n.t(f"flow.risk.{k}.description")}
                  for k in ("easy", "invasive", "risky")},
        "defaults": flows.default_flows(),
    }


@router.get("/api/flows")
async def api_flows_get(request: Request):
    i18n.use_request(request)
    return _payload()


@router.post("/api/flows")
async def api_flows_set(request: Request):
    i18n.use_request(request)
    try:
        body = await request.json()
    except ValueError:
        raise HTTPException(400, i18n.t("flow.error.invalid_body"))
    if not isinstance(body, dict) or not isinstance(body.get("flows"), dict):
        raise HTTPException(400, i18n.t("flow.error.invalid_body"))
    try:
        settings.flows_update(body["flows"])
    except flows.FlowError as exc:
        raise HTTPException(400, i18n.t(exc.key, **exc.params))
    except OSError:
        logger.exception("Salvataggio flussi di ricerca fallito")
        raise HTTPException(500, "Salvataggio non riuscito")
    return _payload()


@router.post("/api/flows/reset")
async def api_flows_reset(request: Request):
    i18n.use_request(request)
    try:
        settings.flows_reset()
    except OSError:
        logger.exception("Ripristino flussi di ricerca fallito")
        raise HTTPException(500, "Salvataggio non riuscito")
    return _payload()
