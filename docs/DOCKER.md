# Vedetta in Docker (Home Assistant Container)

For Home Assistant **Container**, which has no App store. Same app, same image, with a login of its own. Home Assistant **OS** users: install the app instead ([Installation](INSTALLATION.md)), it needs no login and no Docker.

[← Back to the README](../README.md)

## What you need

- **Linux with Docker Engine** and Compose. A Raspberry Pi, a mini PC, a VM or an LXC container (Proxmox: unprivileged, with *nesting* on) are all fine.
- **On the same network as your devices.** Vedetta listens to the LAN itself (ARP, mDNS, DHCP), so it uses the host network.
- **VLANs: a network interface on each one, if you want their MACs.** Without one, Vedetta still sees a VLAN behind the router, by ping: MACs only where Home Assistant knows them, so fewer brands and phones. [Networks](NETWORKS.md)
- **Not supported:** Docker Desktop on Windows or macOS (its host network does not reach the LAN; Home Assistant Container does not support it either) and rootless Docker (its host network is not the LAN).

## Start

```bash
sudo mkdir -p /opt/vedetta && cd /opt/vedetta
sudo curl -fsSLO https://raw.githubusercontent.com/Sived80/vedetta/main/docker-compose.yml
sudo touch ha_token.txt && sudo chmod 600 ha_token.txt   # the Home Assistant token, see below (may stay empty)
sudo nano docker-compose.yml                             # the three lines marked EDIT
sudo docker compose up -d
sudo docker logs vedetta          # FIRST SETUP: ... One-time code, valid 60 minutes: ABCD-EFGH-JKLM
```

Open `http://<host>:8765`, type the code and choose a password (at least 15 characters; a sentence is easier to remember). Then press **Scan network**. Give it a day or two: phones sleep and names are announced now and then.

The code exists only in the log of the container, so only someone who can run Docker on the host can choose the password. It expires after 60 minutes (`docker restart vedetta` prints a new one) and works once.

**Forgot the password?** `docker exec -it vedetta vedetta-passwd` sets a new one and signs out every browser.

## Home Assistant

Vedetta reads names, brands, models and areas from Home Assistant, and sends your alerts through it. It needs an address and a **long-lived access token**:

1. **A user just for Vedetta.** In Home Assistant open your profile and turn on *Advanced mode* (the *Users* tab is hidden without it). Then *Settings → People → Users* tab *→ Add user*: name it *Vedetta*, choose a password, turn on **Local access only**, leave **Administrator off**, *Create*.
2. **Its token.** Log in as that user (a private window of the browser is the easiest way), open its profile → *Security* → *Long-lived access tokens* → *Create token*, name it *vedetta-docker*, and copy it: Home Assistant shows it only once.
3. **Give it to Vedetta.** On the Docker host paste the token in `ha_token.txt` (one line, next to `docker-compose.yml`), check `VEDETTA_HA_URL` (the address of Home Assistant, e.g. `http://192.168.1.10:8123`), then:

   ```bash
   sudo chown root:root ha_token.txt && sudo chmod 600 ha_token.txt
   sudo docker compose up -d
   ```

   The file must be owned by root: the container keeps no capability to read files of other users (if it cannot read it, the log says so).

**Is it connected?** On the page, the *Home Assistant* tile of the carousel at the top says it: green *Connected* with the number of its devices, grey *Not connected*, red *Token refused* or *No answer*; a tap on it shows these steps again. The page also opens them by itself after the login while Home Assistant is not connected (*Do not show again* stops that). In the log: `docker logs vedetta | grep "Home Assistant"` shows *Home Assistant connected: N devices*, or what went wrong.

The token reaches Vedetta as a Compose secret (`/run/secrets/ha_token`): it is not in the environment, so `docker inspect` does not show it, and it never appears in the log, on the page or in an export. `VEDETTA_HA_TOKEN_FILE` can point to another file.

A non-admin user is enough for everything but one switch: **Events in Home Assistant** (the `vedetta_*` events for automations) need an administrator's token, as Home Assistant allows only administrators to fire events. Notifications to your phone work without it.

## Vedetta inside a Home Assistant dashboard

*Settings → Dashboards → Add dashboard → Webpage*, with the address of Vedetta (`http://<host>:8765`). Vedetta lets only the addresses in `VEDETTA_FRAME_ANCESTORS` show it in a frame: put the address of Home Assistant there, as in the example.

- Home Assistant on **HTTPS** needs Vedetta on HTTPS too (a browser does not show an HTTP page inside an HTTPS one): use a reverse proxy, see below.
- The login inside the frame works when Home Assistant and Vedetta are on the **same host** (or the same domain behind a proxy); otherwise the browser keeps the session cookie away from the frame and the page asks the password each time. Open Vedetta in its own tab then.

## Settings

| Variable | Default | What it does |
|---|---|---|
| `VEDETTA_HA_URL` | none | Address of Home Assistant, `http://host:8123` or `https://...`. Without it Vedetta works on its own. |
| `VEDETTA_HA_TOKEN_FILE` | `/run/secrets/ha_token` | File with the long-lived access token. |
| `VEDETTA_PORT` | `8765` | Port of the page. |
| `VEDETTA_BIND` | `0.0.0.0` | Address the page listens on (`127.0.0.1` behind a proxy on the same host). |
| `VEDETTA_FRAME_ANCESTORS` | none | Addresses allowed to show Vedetta in a frame (Home Assistant). |
| `VEDETTA_TRUSTED_PROXIES` | `127.0.0.1` | Reverse proxies whose `X-Forwarded-*` headers are believed. |
| `VEDETTA_ALLOWED_HOSTS` | none | Host names you open Vedetta with, when they are not an IP address, `localhost` or a local name (`.local`, `.lan`, `.home.arpa`, `.internal`). Any other name gets *Host not allowed*: it protects from web pages that point a name of theirs to your LAN (DNS rebinding). |
| `VEDETTA_COOKIE_SECURE` | `auto` | `true` forces the Secure cookie (HTTPS only), `auto` follows the page. |
| `VEDETTA_IFACE` | automatic | Network interface to scan (e.g. `eth0`). |
| `VEDETTA_MQTT_HOST`, `_PORT`, `_USER` | none | MQTT broker (Vedetta publishes its devices with MQTT discovery). Password: `VEDETTA_MQTT_PASSWORD_FILE` or `/run/secrets/mqtt_password`. |
| `VEDETTA_INTERNET_PUBLIC_IP`, `_PATH`, `_MAC_DB`, `_UPDATE_CHECK` | `true` | Switch off one of the four functions that reach the Internet (see [Privacy](PRIVACY.md)). |
| `VEDETTA_NIGHT_HOUR` | `3` | Hour of the nightly maintenance. |
| `VEDETTA_LOG_LEVEL` | `info` | `debug`, `info`, `warning`, `error`. |
| `TZ` | `UTC` | Your time zone, for the times in the log. |

Every secret (`ha_token`, `mqtt_password`) can also be given as a plain variable (`VEDETTA_HA_TOKEN`), but then `docker inspect` shows it: the log says so once. Prefer the file.

## Behind a reverse proxy (HTTPS)

Point the proxy to `http://<host>:8765`, keep the `Host` header (and write that name in `VEDETTA_ALLOWED_HOSTS`) and send `X-Forwarded-Proto`. If the proxy runs on another machine, write its address in `VEDETTA_TRUSTED_PROXIES`: only then Vedetta believes the scheme and the client address it sends (the wait after wrong passwords is counted per client address). On HTTPS the session cookie becomes `__Host-vedetta_session`, Secure. HSTS is for the proxy to send.

Without HTTPS a browser sends the session cookie of Vedetta to every service of the same host, on any port (cookies do not tell ports apart): another web app on that machine could read it. HTTPS behind a proxy avoids it.

Do not expose Vedetta to the Internet: it is a map of your home network. Use a VPN to reach it from outside.

## Update

```bash
cd /opt/vedetta
nano docker-compose.yml          # the new version in the image line, e.g. ghcr.io/sived80/vedetta:1.1.1
docker compose pull && docker compose up -d
```

Vedetta never updates itself. It asks GitHub for the latest release every 12 hours and shows a red dot on the menu when there is one (`VEDETTA_INTERNET_UPDATE_CHECK: "false"` switches the question off). A fixed version in the image line is on purpose: an update is something you choose, not something that happens at a restart. Automatic updaters of `latest` are not recommended.

Every image is built and signed on GitHub from the tagged commit. Anyone can check it:

```bash
gh attestation verify oci://ghcr.io/sived80/vedetta:1.1.0 -R Sived80/vedetta
```

## Backup and removal

Everything Vedetta knows is in `./data`: the devices, their history, the settings and the hash of the password. Back up that folder (it is not part of a Home Assistant backup) and keep it private. To remove Vedetta: `docker compose down`, then delete the folder.

## Security

What the example `docker-compose.yml` does, and why:

- **A login on every page and every call.** No default password: the first one is chosen with the one-time code of the log. Passwords are stored as a scrypt hash (the parameters OWASP recommends), sessions as a digest (a copy of `./data` cannot open one), 12 hours without use or 30 days at most; a new password closes them all. One password check at a time: after five wrong ones from an address each attempt waits longer, up to 15 minutes; all addresses together are slowed down too, but at most 30 seconds, so nobody can keep you out. Only host names of your network are answered (no DNS rebinding).
- **Requests from other sites are refused.** Every change must come from the page of Vedetta itself (Fetch Metadata and Origin, plus a header a form of another site cannot send). Cookies are HttpOnly and SameSite.
- **Network capabilities only.** `cap_drop: ALL`, then just `NET_RAW` (ping, ARP, nmap) and `NET_BIND_SERVICE` (the passive DHCP listener on port 67). No privileged mode, no Docker socket, `no-new-privileges`. The process runs as root inside the container because Nmap and arp-scan are installed when the container starts (their licences keep them out of the published image), but that root has none of the powers of the host's root.
- **The host network**, because a network scanner must see the LAN: ARP, mDNS, DHCP and SSDP do not cross Docker's own networks. Vedetta only watches: it never logs in to a device and never tries a password.
- **Secrets in files**, not in variables. Nothing is sent anywhere but the four Internet functions listed in [Privacy](PRIVACY.md), each one switchable off; no telemetry.
- `/healthz` answers only inside the container (the healthcheck of Compose).

Found a problem? [Report it privately](../SECURITY.md).
