"""scan_format: moved out of scanner.py (see tools/split_module.py)."""
from ..formatters import is_useless_title


def format_scan_info(info: dict) -> dict:
    """Turns the result of full_scan into fields ready to be shown in 'Additional info'."""
    fields = _copy_web_and_name_fields(info)
    _copy_upnp_and_mdns_fields(info, fields)
    _copy_declared_identity_fields(fields, info)
    ports = _build_port_entries(info, fields)
    return _attach_ports_to_fields(ports, fields)


def _copy_web_and_name_fields(info):
    fields = {}
    # The text nmap puts when the page has no real <title>
    # ("Site doesn't have a title (text/html; charset=...)") is not a title,
    # it is a placeholder: showing it as if it were useful information confuses
    # more than it helps. Better to omit it altogether.
    if info.get("http_title") and not is_useless_title(info["http_title"]):
        fields["http_title"] = info["http_title"]
    if info.get("http_server"):
        fields["http_server"] = info["http_server"]
    if info.get("mdns_name"):
        fields["mdns_name"] = info["mdns_name"]
    if info.get("netbios_name"):
        fields["netbios_name"] = info["netbios_name"]
    if info.get("snmp_descr"):
        fields["snmp_descr"] = info["snmp_descr"]
    return fields


def _copy_upnp_and_mdns_fields(info, fields):
    if info.get("upnp_name"):
        fields["upnp_name"] = info["upnp_name"]
    if info.get("upnp_manufacturer"):
        fields["upnp_manufacturer"] = info["upnp_manufacturer"]
    if info.get("upnp_model"):
        fields["upnp_model"] = info["upnp_model"]
    if info.get("mdns_model"):
        fields["mdns_model"] = info["mdns_model"]
    if info.get("mdns_manufacturer"):
        fields["mdns_manufacturer"] = info["mdns_manufacturer"]


def _copy_declared_identity_fields(fields, info):
    for key in ("onvif_name", "onvif_hardware", "onvif_manufacturer", "wsd_types", "rtsp_server",
                "tls_subject", "tls_issuer", "ssh_hostkey", "api_source", "api_vendor", "api_model", "api_name",
                "api_fw", "mdns_services", "igmp_groups"):
        if info.get(key):
            fields[key] = info[key]
    if info.get("battery") in ("yes", "no"):
        fields["battery"] = info["battery"]
    if info.get("full_ports_at"):
        fields["full_ports_at"] = info["full_ports_at"]
    if info.get("services_at"):
        fields["services_at"] = info["services_at"]


def _build_port_entries(info, fields):
    if info.get("slow_scan"):
        fields["slow_scan"] = True  # slow device: the next scans use the targeted ports

    ports = []
    for p in info.get("ports", []):
        label = f"{p['port']} · {p['product']}" if p.get("product") else (
            f"{p['port']} · {p['service']}" if p.get("service") else str(p["port"])
        )
        item = {
            "label": label,
            "confirmed": bool(p.get("confirmed")),
            "category": _categorize_port(p["port"], p.get("service")),
        }
        if "web_ui" in p:   # the page was really requested: does it answer with something a person can open?
            item["web_ui"] = bool(p["web_ui"])
            item["web_scheme"] = p.get("web_scheme") or "http"
        ports.append(item)
    return ports


def _categorize_port(port: int, service: str | None) -> str:
    return next((category for category, ports, services in _PORT_CATEGORY_RULES if port in ports or (service and service in services)), "other")


def _attach_ports_to_fields(ports, fields) -> dict:
    if ports:
        fields["ports"] = ports
    return fields


# Service categories for coloring the "scanned ports" in Additional info:
# grouped by function (web interface, remote access, automation/IoT,
# network infrastructure, file sharing, databases) rather than by individual
# protocol - a port OR a service name recognized in a group is enough
# to classify it (the name is for non-standard ports detected by -sV in
# full_scan, the number for deep_scan which does not do version detection). Everything
# else falls into "other".
_PORT_CATEGORY_RULES: list[tuple[str, set[int], set[str]]] = [
    ("media", {554, 1935, 7000, 8008, 8009, 1400, 8060, 32400, 8096, 8200},
     {"rtsp", "rtmp", "airplay", "airtunes", "dlna", "upnp"}),
    ("print", {631, 9100, 515}, {"ipp", "jetdirect", "printer", "pdl-datastream"}),
    ("vpn", {1194, 51820, 500, 4500, 1701, 1723}, {"openvpn", "isakmp", "ipsec", "l2tp", "pptp", "wireguard"}),
    ("mail", {25, 465, 587, 110, 995, 143, 993}, {"smtp", "smtps", "submission", "pop3", "pop3s", "imap", "imaps"}),
    ("web", {80, 443, 3000, 8080, 8081, 8443, 8888, 9000, 9090, 8123, 8006},
     {"http", "https", "http-alt", "http-proxy", "https-alt", "www", "sun-answerbook"}),
    ("remote", {22, 23, 3389, 5900, 5555, 5985, 5986},
     {"ssh", "telnet", "rdp", "ms-wbt-server", "vnc", "adb", "wsman"}),
    ("iot", {1883, 8883, 5683, 6053},
     {"mqtt", "secure-mqtt", "coap"}),
    ("infra", {53, 67, 68, 111, 123, 137, 138, 139, 161, 162, 389, 5353, 5355},
     {"domain", "dhcps", "dhcpc", "rpcbind", "ntp", "snmp", "snmptrap", "ldap", "mdns", "llmnr"}),
    ("file", {21, 445, 548, 2049},
     {"ftp", "microsoft-ds", "netbios-ssn", "afpovertcp", "nfs"}),
    ("db", {3306, 5432, 6379, 27017, 1433},
     {"mysql", "postgresql", "redis", "mongodb", "ms-sql-s"}),
]
