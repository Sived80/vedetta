# Multi-architecture image: the Supervisor picks the architecture (the "arch" key).
FROM ghcr.io/home-assistant/base:latest

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
