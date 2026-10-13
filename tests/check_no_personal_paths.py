"""No file tracked by Git may carry the trace of a local machine (a stray local file, a measurement database, a path in a log): the repository is public.
The check looks for the SHAPE of such a trace, never for a name, so no name has to be written in the repository: the home folder of a user (C:\\Users\\<who>,
/home/<who>, /Users/<who>) and the cloud folder that a company account creates on a PC (the cloud service, a dash, the company). Every tracked file is read as bytes, so binary files count too."""
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# the folders that every machine has, and the placeholders and CI users that are no one in particular (compared in lower case)
GENERIC = {"public", "default", "all users", "default user", "user", "username", "name", "runner"}
SHAPES = {
    "windows home folder": re.compile(rb"[A-Za-z]:[\\/]+Users[\\/]+([^\\/\s\"'<>|:*?]+)"),
    "unix home folder": re.compile(rb"(?<![A-Za-z0-9_.-])/(?:home|Users)/([A-Za-z0-9._-]+)"),
    "synced company folder": re.compile(rb"OneDrive\s+-\s+([^\\/\r\n\"']{1,40})"),
}


def personal_traces(data: bytes) -> list[str]:
    """The names of the shapes found in `data` (also in UTF-16 text), leaving out the generic folders and placeholders."""
    found = []
    for text in {data, data.replace(b"\x00", b"")}:
        for label, shape in SHAPES.items():
            if any(m.group(1).decode("latin-1").strip().lower() not in GENERIC for m in shape.finditer(text)):
                found.append(label)
    return sorted(set(found))


# the samples are written in pieces, so that this very file does not carry the shapes it looks for
DRIVE, USERS, HOME, SYNC = "C" + ":\\", "Us" + "ers", "/ho" + "me/", "One" + "Drive - "
assert personal_traces((DRIVE + USERS + "\\someone\\file.txt").encode()) == ["windows home folder"]
assert "windows home folder" in personal_traces((DRIVE.replace("\\", "/") + USERS + "/someone/file.txt").encode()), "forward slashes count (it is also a unix shape: both are told)"
assert personal_traces((DRIVE + "\\" + USERS + "\\\\someone").encode()) == ["windows home folder"], "doubled backslashes (a JSON or a Python string) count too"
assert personal_traces((DRIVE + USERS + "\\someone").encode("utf-16-le")) == ["windows home folder"], "UTF-16 text counts too"
assert personal_traces((HOME + "someone/.ssh").encode()) == ["unix home folder"]
assert personal_traces((SYNC + "Some Company\\Docs").encode()) == ["synced company folder"]
assert personal_traces((DRIVE + USERS + "\\Public\\x " + HOME + "runner/work " + DRIVE + USERS + "\\<user>\\x " + HOME + "user/x").encode()) == []
assert personal_traces(b"") == [] and personal_traces(b"no path here, a/home that is not one, ers/x") == []

try:
    files = subprocess.run(["git", "ls-files", "-z"], cwd=ROOT, capture_output=True, check=True).stdout.decode("utf-8").split("\0")
except (OSError, subprocess.CalledProcessError):
    print("SKIP: git is not available")
    sys.exit(0)

bad = []
for rel in filter(None, files):
    path = ROOT / rel
    if not path.is_file() or path.stat().st_size > 20_000_000:
        continue
    for label in personal_traces(path.read_bytes()):
        bad.append((rel, label))
assert not bad, "files that carry the trace of a local machine (a home folder or a synced company folder): " + ", ".join(f"{r} ({w})" for r, w in bad[:8])
print("TUTTO OK")
