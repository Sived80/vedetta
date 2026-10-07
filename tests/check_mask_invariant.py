"""The safety check and the masking must agree: whatever the masking leaves on purpose (multicast groups, public DNS, version
numbers...) the check must not call a leak, or the export refuses to run for nothing (it did, for people whose log mentioned
239.255.255.250). And what the masking cannot leave must never be accepted."""
import os
import random
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app.export import anonymize  # noqa: E402

a = anonymize.Anonymizer()
for ip in ("192.168.1.5", "10.0.0.9", "172.20.4.7"):
    a.add_ip(ip)
a.add_mac("f0:18:98:aa:bb:cc")
a.add_device(["Anna's iPhone", "giulia-ipad", "Salotto TV Samsung"], "phone")
a.add_public_ip("93.184.216.34")

# lines of the kind the app, the scans and the registries really write
SAFE = [
    "SSDP M-SEARCH to 239.255.255.250:1900", "mDNS query to 224.0.0.251:5353", "multicast 224.0.0.1 and 224.0.0.22", "DHCP discover 255.255.255.255",
    "listening on 0.0.0.0:8765", "127.0.0.1 localhost", "link-local 169.254.12.7", "CGNAT hop 100.64.0.1", "dns 1.1.1.1 8.8.8.8 8.8.4.4 9.9.9.9 94.140.14.14",
    "Server: lighttpd/1.4.55", "nginx/1.18.0 on Linux 5.10.0.1", "fw v10.0.1.2 and firmware 2.4.1.0 and version: 3.1.0.9", "ratio 1.2.3.4.5 and oid 1.3.6.1.2.1.1.1.0",
    "ipv6 group ff02::c, fe80::1%eth0, 2001:db8::1", "uuid 3f2504e0-4f89-11d3-9a0c-0305e82c3301", "serial 0123456789ab", "model XR-55X92K",
    "ssh 256 9b:e9:0b:ab:cd:ef:01:23:45:67:89:ab:cd:ef:aa:bb (ECDSA)", "network 172.16.0.0/12, 192.168.0.0/16, 10.0.0.0/8", "gateway 192.168.0.1, dns 192.168.0.1",
    "time 12:34:56.789 on 2026-10-06 10-06-12-30", "ptr 4.3.2.1.in-addr.arpa", "80/tcp open http nginx 1.18.0 (Ubuntu)", "ntp 216.239.35.0 and 17.253.14.125",
    "update from 52.84.123.4", "hostname=Android-1234abcd", "ssid HomeWifi bssid 00:11:22:33:44:55", "contact admin@example.org", "password: **** token=abc123",
    "id scan-192-168-1-5, scan_192_168_1_5, scan-172-20-4-7, host-192-168-77-1", "from 192.168.1.5 to 192.168.1.5.1 and 172.16.1.2.3",
    "mac:F0:18:98:AA:BB:CC bssid=f0-18-98-aa-bb-cc ether f0:18:98:aa:bb:cc, hwaddr:F0:18:98:AA:BB:CC.", "Server: 93.184.216.34 and DHCP DISCOVER: 93.184.216.34",
    "Anna's iPhone joined, giulia-ipad left, Salotto TV Samsung is on, F0:18:98:AA:BB:CC", "public 93.184.216.34 and a hop 81.174.0.21",
]
for line in SAFE:
    out = a.text(line)
    assert a.leaks(out) == [], (line, out, a.leaks(out))

# a MAC is six pairs: a longer run (an SSH fingerprint, an EUI-64) is not touched, a MAC after a word and a colon is
assert a.text("fp 9b:e9:0b:ab:cd:ef:01:23 and 9b-e9-0b-ab-cd-ef-01-02") == "fp 9b:e9:0b:ab:cd:ef:01:23 and 9b-e9-0b-ab-cd-ef-01-02"      # eight pairs: not a MAC
assert "f0:18:98:aa:bb:cc" not in a.text("mac:f0:18:98:aa:bb:cc").lower() and "f0:18:98:aa:bb:cc" not in a.text("seen,F0:18:98:AA:BB:CC;").lower()
assert a.leaks("mac:f0:18:98:aa:bb:cc") == ["MAC address"] and a.leaks("x f0-18-98-aa-bb-cc.") == ["MAC address"]

# and the other way: what must not be left is found
for line, kind in [("host 192.168.9.9 up", "home network address"), ("id scan-192-168-9-9", "home network address"), ("mac f0:18:98:aa:bb:cc", "MAC address"),
                   ("owner Anna's iPhone", "name"), ("from 81.174.0.21", "public address"), ("mail a@b.it", "email address"), ("token=abcdefgh", "password or token")]:
    assert kind in a.leaks(line), (line, a.leaks(line))

# random lines: whatever mix of addresses, the check agrees with the masking
rng = random.Random(7)
parts = ["192.168.%d.%d", "172.%d.%d.9", "10.%d.0.%d", "%d.%d.%d.%d", "239.255.%d.%d", "224.0.%d.%d", "100.64.%d.%d", "169.254.%d.%d", "0.0.%d.%d"]
for _ in range(3000):
    seed = rng.choice(parts)
    n = seed.count("%d")
    ip = seed % (rng.randint(10, 40), rng.randint(0, 255)) if seed.startswith("172.") else seed % tuple(rng.randint(0, 255) for _ in range(n))
    sep = rng.choice([".", "-", "_"])
    line = f"x {ip.replace('.', sep)} y {rng.choice(['via', 'to', 'v', 'version', 'fw'])} {ip} z"
    out = a.text(line)
    assert a.leaks(out) == [], (line, out, a.leaks(out))
print("TUTTO OK")
