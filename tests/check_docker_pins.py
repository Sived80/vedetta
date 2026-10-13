"""The image of the add-on is built the same way every time: the base image is named by a version tag AND by its digest (a tag can be moved by whoever publishes it, a digest cannot), never "latest", and every Python
package is pinned with "==". Without it two builds of the same version of the app could differ, and a fix for one user could not be rebuilt for another. How to move to a newer base on purpose is written in the Dockerfile."""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent / "vedetta"


def problems(dockerfile: str, requirements: str) -> list[str]:
    found = []
    froms = [ln.split("#")[0].strip() for ln in dockerfile.splitlines() if ln.strip().upper().startswith("FROM ")]
    if not froms:
        found.append("no FROM line")
    for ln in froms:
        image = ln.split()[1]
        tag = image.split("@")[0].partition(":")[2]
        if not tag or tag == "latest":
            found.append("the base image is not pinned by a version tag: " + ln)
        if not re.search(r"@sha256:[0-9a-f]{64}$", image):
            found.append("the base image is not pinned by its digest: " + ln)
    for ln in requirements.splitlines():
        ln = ln.split("#")[0].strip()
        if ln and not re.match(r"^[A-Za-z0-9_.\-]+(\[[^\]]+\])?==[0-9A-Za-z_.\-+!]+$", ln):
            found.append("the package is not pinned with ==: " + ln)
    return found


DIGEST = "sha256:" + "ab" * 32
assert problems("FROM ghcr.io/x/base:3.24-2026.10.0@%s\n" % DIGEST, "fastapi==0.115.0\nuvicorn[standard]==0.30.6\n") == []
assert problems("FROM ghcr.io/x/base:latest\n", "") and problems("FROM ghcr.io/x/base\n", ""), "latest or no tag"
assert problems("FROM ghcr.io/x/base:3.24\n", ""), "a tag without digest"
assert problems("FROM ghcr.io/x/base@%s\n" % DIGEST, ""), "a digest without tag"
assert problems("RUN true\n", ""), "no FROM"
assert problems("FROM ghcr.io/x/base:3.24@%s\n" % DIGEST, "fastapi>=0.1\n") and problems("FROM ghcr.io/x/base:3.24@%s\n" % DIGEST, "fastapi\n"), "unpinned package"

real = problems((ROOT / "Dockerfile").read_text(encoding="utf-8"), (ROOT / "requirements.txt").read_text(encoding="utf-8"))
assert not real, real
print("TUTTO OK")
