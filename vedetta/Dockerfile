# SPDX-License-Identifier: GPL-3.0-only — additional terms in NOTICE
# Multi-architecture image: the Supervisor picks the architecture (the "arch" key).
# The base image is pinned by its version (the tag: Alpine 3.24 and the release of the base) AND by its digest, so every build of this version of the app starts from the same image (a tag can be moved by whoever
# publishes it, a digest cannot). The digest is of the multi-architecture index (amd64, arm64). To move to a newer base on purpose: look for the tag in the list of ghcr.io/home-assistant/base,
# read its digest (the header docker-content-digest of the manifest), change both here, build on the debug copy and run tests/check_docker_pins.py.
FROM ghcr.io/home-assistant/base:3.24-2026.11.0@sha256:58422480a299b16b6ea376c2167463206d430619ed02b40cd687c8bd6875519e

# Nmap and arp-scan are NOT installed here: run.sh installs them from Alpine when the app starts on Home Assistant, so the published image
# never carries them (the Nmap licence, NPSL section 3, binds a program made to run Nmap that is distributed WITH Nmap; decision C, 20/11).
RUN apk add --no-cache python3 py3-pip iputils curl bash

WORKDIR /app

# Dependencies go in a venv (Alpine does not allow pip in the system Python).
# requirements.txt, VERSION and app/ sit next to this file.
COPY requirements.txt /app/requirements.txt
RUN python3 -m venv /opt/venv \
    && /opt/venv/bin/pip install --no-cache-dir -r /app/requirements.txt

COPY VERSION /app/VERSION
COPY LICENSE NOTICE /app/
COPY app /app/app
COPY run.sh docker-run.sh install-tools.sh /
COPY vedetta-passwd /usr/local/bin/vedetta-passwd
RUN chmod a+x /run.sh /docker-run.sh /install-tools.sh /usr/local/bin/vedetta-passwd
# Docker (Home Assistant Container): the page of the app; under the Supervisor the port is the ingress one and this changes nothing.
EXPOSE 8765

CMD ["/run.sh"]
