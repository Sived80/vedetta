"""The export of the data for analysis (/api/export*): the file in one go, the estimate of the window, and the export as a job that is followed step by step and whose file is taken once. Moved out of
routes/ha.py (the global review asked for it): these routes have one task and share nothing with the pages and the JSON of the dashboard."""
import asyncio
import secrets
import time

from fastapi import APIRouter, HTTPException, Request

from ..applog import logger
from ..export import export_zip as export, report_crypto
from ..export import export_engine
from ..export import export_jobs
from ..export import network_survey
from .bodies import json_dict

router = APIRouter()


@router.post("/api/export")
async def api_export(plain: bool = False):
    """Zip for analysis (data, state and reasons of every device), anonymised. By default it is encrypted with the
    maintainer's public key (safe to attach to a public issue); ?plain=1 gives the plain zip. POST: so it is not
    downloaded by accident through a link."""
    from fastapi.responses import JSONResponse, Response
    headers = {"Cache-Control": "no-store"}
    try:
        data = await asyncio.to_thread(export.build_zip)
        headers["X-Vedetta-Omitted"] = str(len(export.last_omitted))      # files left out because they could not be masked safely
    except export.MaskingFailed as exc:
        logger.warning("Export refused: the masking left something readable (%s)", exc)    # kinds and file only, never values
        return JSONResponse({"error": "masking_failed"}, status_code=422, headers=headers)
    except Exception:                                  # whatever else goes wrong: the reason is in the log, the person gets a clear answer
        logger.exception("Export failed")
        return JSONResponse({"error": "export_failed"}, status_code=500, headers=headers)
    if plain:
        name = "vedetta-analisi-" + time.strftime("%Y%m%d-%H%M%S") + ".zip"
        return Response(content=data, media_type="application/zip", headers={**headers, "Content-Disposition": f'attachment; filename="{name}"'})
    try:
        sealed = await asyncio.to_thread(report_crypto.seal, data)
    except report_crypto.CryptoUnavailable:
        return JSONResponse({"error": "encryption_unavailable"}, status_code=501, headers=headers)   # never a plain file by mistake
    name = "vedetta-report-" + secrets.token_hex(3) + ".txt"      # neutral name: no date, no device
    return Response(content=sealed, media_type="text/plain", headers={**headers, "Content-Disposition": f'attachment; filename="{name}"'})


# ---- the export window: an estimate, a job followed step by step, the file once
@router.get("/api/export/info")
async def api_export_info():
    """Bytes of raw data for each of the last days, what the file always has, and the limit: the window draws the columns and
    says how big a period will be with these; `survey` tells whether the window may offer the network survey."""
    return {**await asyncio.to_thread(export_engine.estimate), "survey": network_survey.ENABLED}


@router.post("/api/export/survey/check")
async def api_export_survey_check():
    """The check button of the network option: is there anything to include? {"state": "ok"|"none"|"noha", "clients": N}, numbers and a state, never a name or an address.
    POST: it reads Home Assistant, so a link must not start it. 404 while the survey is off."""
    if not network_survey.ENABLED:
        raise HTTPException(404, "the network survey is off")
    return await asyncio.to_thread(network_survey.check)


def _job_or_404(job_id: str):
    job = export_jobs.get(job_id)
    if job is None:
        raise HTTPException(404, "export not found")
    return job


def _survey_flag(body: dict, dest: str) -> bool:
    """The tick of the network survey: a yes or a no, and a yes only for the developer export while the survey is on."""
    flag = body.get("survey", False)
    if not isinstance(flag, bool):
        raise HTTPException(422, "survey must be true or false")
    if flag and (dest != "dev" or not network_survey.ENABLED):
        raise HTTPException(422, "the network survey is only for the developer export, and only while it is on")
    return flag


@router.post("/api/export/jobs")
async def api_export_job_start(request: Request):
    """Body: {"dest": "dev"|"me", "from_day": N, "to_day": M} (days ago: the oldest and the newest included, 0 = today) or
    {"dest": ..., "all": true} for the whole history; "survey": true adds the network survey (developer export only)."""
    body = await json_dict(request)
    dest = body.get("dest")
    if dest not in ("dev", "me"):
        raise HTTPException(422, "dest must be dev or me")
    survey = _survey_flag(body, dest)
    if body.get("all") is True:
        first = last = None
    else:
        try:
            first, last = int(body["from_day"]), int(body.get("to_day", 0))
        except (KeyError, TypeError, ValueError):
            raise HTTPException(422, "from_day and to_day must be numbers") from None
        if not (0 <= last <= first < export_engine.HORIZON_DAYS):
            raise HTTPException(422, "period out of range")
    try:
        job = export_jobs.start(dest, first, last, survey)
    except export_jobs.Busy:
        raise HTTPException(409, "an export is already running") from None
    return export_jobs.snapshot(job)


@router.get("/api/export/jobs/{job_id}")
async def api_export_job(job_id: str):
    return export_jobs.snapshot(_job_or_404(job_id))


@router.post("/api/export/jobs/{job_id}/choices")
async def api_export_job_choices(job_id: str, request: Request):
    """Body: {"choices": {"0": "rm", "1": "keep"}}: what to do with each value the check could not fix."""
    job = _job_or_404(job_id)
    body = await json_dict(request)
    try:
        export_jobs.decide(job, body.get("choices") or {})
    except export_jobs.Busy:
        raise HTTPException(409, "nothing to decide") from None
    return export_jobs.snapshot(job)


@router.post("/api/export/jobs/{job_id}/file")
async def api_export_job_file(job_id: str):
    """The finished file, once. POST so it is not downloaded by accident through a link."""
    from fastapi.responses import Response
    got = export_jobs.take(_job_or_404(job_id))
    if got is None:
        raise HTTPException(409, "the file is not ready")
    data, name, mime = got
    return Response(content=data, media_type=mime, headers={"Cache-Control": "no-store", "Content-Disposition": f'attachment; filename="{name}"'})


@router.delete("/api/export/jobs/{job_id}")
async def api_export_job_cancel(job_id: str):
    export_jobs.forget(job_id)
    return {"ok": True}
