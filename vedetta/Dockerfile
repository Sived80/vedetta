# Immagine multi-architettura: l'architettura la sceglie il Supervisor (chiave "arch").
FROM ghcr.io/home-assistant/base:latest

RUN apk add --no-cache python3 py3-pip arp-scan nmap nmap-scripts iputils curl bash

WORKDIR /app

# Dipendenze in un venv (Alpine non permette pip nel Python di sistema).
# requirements.txt, VERSION e app/ li prepara tools/build_addon.py.
COPY requirements.txt /app/requirements.txt
RUN python3 -m venv /opt/venv \
    && /opt/venv/bin/pip install --no-cache-dir -r /app/requirements.txt

COPY VERSION /app/VERSION
COPY app /app/app
COPY run.sh /run.sh
RUN chmod a+x /run.sh

CMD ["/run.sh"]
