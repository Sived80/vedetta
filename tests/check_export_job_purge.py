# SPDX-License-Identifier: GPL-3.0-only — additional terms in NOTICE
"""An export that takes longer than MAX_AGE must not be forgotten while it is still running: the window polled a job that was gone (404,
"export failed" after 15 minutes) and a second export could start next to the first. The age counts from the job's last step, so a job
that has just stopped to ask the person (or has just finished) gets its full time too. No export runs here: the jobs are made by hand."""
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app.export import export_jobs as J  # noqa: E402

OLD = time.time() - J.MAX_AGE - 60


def job(status, last_step_age=None):
    j = J.Job("dev", None, None)
    j.created = OLD
    j.status = status
    if last_step_age is not None:
        j.note("mask")
        j.touched = time.time() - last_step_age
    else:
        j.touched = OLD
    J._jobs[j.id] = j
    return j


# a slow export, started 16 minutes ago, still masking: kept, and it still blocks a second export
slow = job("running", last_step_age=J.MAX_AGE + 60)
assert J.get(slow.id) is slow, "a running export was forgotten"
try:
    J.start("me", None, None)
    raise AssertionError("a second export started next to a running one")
except J.Busy:
    pass

# a job that started long ago but stopped to ask the person a minute ago: kept
asking = job("choose", last_step_age=60)
assert J.get(asking.id) is asking, "a job waiting for the person was forgotten right after its last step"

# idle for longer than MAX_AGE and not running: forgotten (the masked files must not stay around)
idle = job("done", last_step_age=J.MAX_AGE + 60)
assert J.get(idle.id) is None
failed = job("error")
assert J.get(failed.id) is None

# the slow export finishes: from then on it ages like the others
slow.status = "done"
assert J.get(slow.id) is None

print("OK export job purge")
