# Multi-architecture image: the Supervisor picks the architecture (the "arch" key).
# The base image is pinned by its version (Alpine 3.24, release 2026.10.0) AND by its digest, so every build of this version of the app starts from the same image (a tag can be moved by whoever
# publishes it, a digest cannot). The digest is of the multi-architecture index (amd64, arm64). To move to a newer base on purpose: look for the tag in the list of ghcr.io/home-assistant/base,
# read its digest (the header docker-content-digest of the manifest), change both here, build on the debug copy and run tests/check_docker_pins.py.
FROM ghcr.io/home-assistant/base:3.24-2026.10.0@sha256:8fde4170393bdf7a121ea4d6e34b417e1d0b90125948459f9f9f70cdf5d77c16

RUN apk add --no-cache python3 py3-pip arp-scan nmap nmap-scripts iputils curl bash

WORKDIR /app

# Dependencies go in a venv (Alpine does not allow pip in the system Python).
# requirements.txt, VERSION and app/ sit next to this file.
COPY requirements.txt /app/requirements.txt
RUN python3 -m venv /opt/venv \
    && /opt/venv/bin/pip install --no-cache-dir -r /app/requirements.txt

COPY VERSION /app/VERSION
COPY app /app/app
COPY run.sh /run.sh
RUN chmod a+x /run.sh

CMD ["/run.sh"]
