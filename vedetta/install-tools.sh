#!/bin/sh
# SPDX-License-Identifier: GPL-3.0-only — additional terms in NOTICE
# Nmap and arp-scan are not in the published image (their licences: THIRD_PARTY_NOTICES.md, decision C of 20/11): they are installed
# from Alpine Linux when the container starts the first time (and after an update, which makes a new container); a restart of the same
# container finds them. A failed install does not stop the app: it starts without them and the install is tried again every 10 minutes.
# Used by run.sh (app of Home Assistant) and docker-run.sh (Docker). $1 = the command that writes a line in the log.
log="${1:-echo}"
tools_missing() { ! command -v nmap > /dev/null 2>&1 || ! command -v arp-scan > /dev/null 2>&1; }
install_tools() { apk add --no-cache --quiet nmap nmap-scripts arp-scan; }
if tools_missing; then
    "$log" "Installing nmap and arp-scan from Alpine Linux"
    for try in 1 2 3; do
        if install_tools; then break; fi
        sleep 10
    done
    if tools_missing; then
        "$log" "nmap and arp-scan could not be installed (no internet?): Vedetta starts without them and tries again every 10 minutes"
        ( while sleep 600; do if install_tools; then "$log" "nmap and arp-scan installed"; break; fi; done ) &
    fi
fi
