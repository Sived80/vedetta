"""scan_cert: moved out of scanner.py (see tools/split_module.py)."""


def parse_ssl_cert(output: str) -> tuple[str | None, str | None]:
    """Subject and issuer of the certificate (ssl-cert text)."""
    subject = issuer = None
    for line in output.splitlines():
        line = line.strip()
        if line.startswith("Subject:") and subject is None:
            subject = line[8:].strip()[:160] or None
        elif line.startswith("Issuer:") and issuer is None:
            issuer = line[7:].strip()[:160] or None
    return subject, issuer


def parse_ssh_hostkey(output: str) -> str | None:
    """First fingerprint of the host key (ssh-hostkey text): it stays the same even
    if the device changes IP."""
    for line in output.splitlines():
        line = line.strip()
        if line and line[0].isdigit():
            return line[:120]
    return None


_DER_NAME_OIDS = {bytes.fromhex("550403"): "commonName", bytes.fromhex("55040a"): "organizationName",
                   bytes.fromhex("55040b"): "organizationalUnitName"}


def cert_subject(der: bytes) -> str | None:
    """Subject of an X.509 certificate (DER) in nmap's ssl-cert format:
    "commonName=pve.local/organizationName=Proxmox Virtual Environment". Only CN, O and OU."""
    try:
        _, c, _ = _der_item(der, 0)                  # Certificate
        _, c, _ = _der_item(der, c)                  # TBSCertificate
        tag, s, e = _der_item(der, c)
        if tag == 0xA0:                              # version [0] optional
            c = e
        for _ in range(4):                           # serial, signature, issuer, validity
            _, _, c = _der_item(der, c)
        _, c, end = _der_item(der, c)                # subject (sequence of RDNs)
        parts = []
        while c < end:
            _, rs, re_ = _der_item(der, c)           # RDN (set)
            _, as_, _ = _der_item(der, rs)           # AttributeTypeAndValue
            _, os_, oe = _der_item(der, as_)         # OID
            key = _DER_NAME_OIDS.get(der[os_:oe])
            _, vs, ve = _der_item(der, oe)
            if key:
                parts.append(f"{key}={der[vs:ve].decode('utf-8', 'ignore')}")
            c = re_
        return "/".join(parts)[:160] or None
    except (IndexError, ValueError):
        return None


def _der_item(buf: bytes, pos: int) -> tuple[int, int, int]:
    """(tag, content start, content end) of the DER element in buf[pos:]."""
    tag, ln = buf[pos], buf[pos + 1]
    pos += 2
    if ln & 0x80:
        n = ln & 0x7F
        ln = int.from_bytes(buf[pos:pos + n], "big")
        pos += n
    return tag, pos, pos + ln
