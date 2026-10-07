"""The export of the window, as a job the window follows step by step: it is started, polled (which steps are done, what the
check found), the person decides what could not be fixed, and the file is taken once. One job at a time, kept in memory and
forgotten after a while (the masked files of an export must not stay around)."""
import secrets
import threading
import time

from .applog import logger
from . import export_engine as E, report_crypto

MAX_AGE = 15 * 60
SHOWN = 10                       # the values the window lists; the rest follow "remove all"


class Busy(RuntimeError):
    pass


class Job:
    def __init__(self, dest: str, first_day: int | None, last_day: int | None) -> None:
        self.id = secrets.token_urlsafe(12)
        self.dest, self.first_day, self.last_day = dest, first_day, last_day
        self.status = "running"            # running | choose | done | error
        self.steps: list[str] = []
        self.error: str | None = None
        self.prepared = None
        self.pending: list[dict] = []
        self.fixed = 0
        self.result: bytes | None = None
        self.filename = self.mime = ""
        self.created = time.time()
        self.lock = threading.Lock()

    def note(self, step: str) -> None:
        with self.lock:
            self.steps.append(step)

    def close(self) -> None:
        if self.prepared is not None:
            self.prepared.close()
            self.prepared = None


_jobs: dict[str, Job] = {}
_guard = threading.Lock()


def _purge() -> None:
    for jid, job in list(_jobs.items()):
        if time.time() - job.created > MAX_AGE:
            job.close()
            _jobs.pop(jid, None)


def start(dest: str, first_day: int | None, last_day: int | None) -> Job:
    with _guard:
        _purge()
        if any(j.status == "running" for j in _jobs.values()):
            raise Busy("an export is already running")
        job = Job(dest, first_day, last_day)
        _jobs[job.id] = job
    threading.Thread(target=_run, args=(job,), daemon=True, name="export-" + job.id[:6]).start()
    return job


def _fail(job: Job, code: str) -> None:
    job.error, job.status = code, "error"
    job.close()


def _run(job: Job) -> None:
    try:
        job.prepared = E.prepare(job.dest, job.first_day, job.last_day, progress=job.note)
        job.fixed = job.prepared.fixed
        if job.prepared.pending:
            job.pending = job.prepared.pending
            job.status = "choose"
            return
        _finish(job, {})
    except Exception:
        logger.exception("Export failed")                     # the reason goes to the log, the window gets a short code
        _fail(job, "export_failed")


def _finish(job: Job, choices: dict) -> None:
    try:
        job.note("seal" if job.dest == "dev" else "prepare")
        data = E.finish(job.prepared, choices)
        if job.dest == "dev":
            try:
                data = report_crypto.seal(data)
            except report_crypto.CryptoUnavailable:
                return _fail(job, "encryption_unavailable")   # never a plain file by mistake
            if len(data) > E.LIMIT_BYTES:
                return _fail(job, "too_big")
            job.filename, job.mime = "vedetta-report-" + secrets.token_hex(3) + ".txt", "text/plain"
        else:
            job.filename, job.mime = "vedetta-analisi-" + time.strftime("%Y%m%d-%H%M%S") + ".zip", "application/zip"
        job.result = data
        job.note("ready")
        job.status = "done"
        job.close()
    except Exception:
        logger.exception("Export failed")
        _fail(job, "export_failed")


def get(job_id: str) -> Job | None:
    _purge()
    return _jobs.get(job_id)


def snapshot(job: Job) -> dict:
    with job.lock:
        steps = list(job.steps)
    out = {"id": job.id, "dest": job.dest, "status": job.status, "steps": steps, "fixed": job.fixed, "error": job.error,
           "items_total": len(job.pending), "items": [{k: it[k] for k in ("id", "kind", "value", "file", "where")} for it in job.pending[:SHOWN]]}
    if job.result is not None:
        out.update(size=len(job.result), filename=job.filename)
    return out


def decide(job: Job, choices: dict) -> None:
    """The person chose what to do with the values that could not be fixed ("rm" or "keep" for each id; the ones that are not
    listed in the window follow "rm")."""
    if job.status != "choose":
        raise Busy("nothing to decide")
    job.status = "running"
    clean = {int(k): ("keep" if v == "keep" else "rm") for k, v in (choices or {}).items() if str(k).isdigit()}
    threading.Thread(target=_finish, args=(job, clean), daemon=True, name="export-" + job.id[:6]).start()


def take(job: Job) -> tuple[bytes, str, str] | None:
    """The file, once: the job is forgotten right after."""
    if job.status != "done" or job.result is None:
        return None
    out = (job.result, job.filename, job.mime)
    forget(job.id)
    return out


def forget(job_id: str) -> None:
    with _guard:
        job = _jobs.pop(job_id, None)
    if job is not None:
        job.close()
        job.result = None
