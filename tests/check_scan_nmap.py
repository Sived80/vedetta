"""Reference test of scan/scan_nmap.py with a fake nmap: the XML is read as it is written by nmap (hosts up/down, confirmed services, web title,
TLS certificate, SSH key), the command lines are the ones the pipeline relies on, the pilot decides "slow", a scan that ends at its host-timeout is
remembered as incomplete, a cancelled scan kills the process, and the readable labels of the log."""
import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app.scan import scan_nmap as nm  # noqa: E402

XML = """<?xml version="1.0"?><nmaprun>
<host><status state="up"/><address addr="10.0.0.5" addrtype="ipv4"/><address addr="AA:BB:CC:00:00:05" addrtype="mac" vendor="Acme"/>
 <hostnames><hostname name="nas.local"/></hostnames>
 <ports>
  <port protocol="tcp" portid="80"><state state="open"/><service name="http" product="nginx" version="1.2" method="probed"/>
   <script id="http-title" output="My NAS"/></port>
  <port protocol="tcp" portid="443"><state state="open"/><service name="https" method="table"/>
   <script id="ssl-cert" output="Subject: commonName=nas.local/organizationName=Acme&#10;Issuer: commonName=Acme CA"/></port>
  <port protocol="tcp" portid="22"><state state="open"/><service name="ssh" method="probed"/>
   <script id="ssh-hostkey" output="256 aa:bb:cc (ED25519)"/></port>
  <port protocol="tcp" portid="23"><state state="closed"/><service name="telnet"/></port>
 </ports></host>
<host><status state="down"/><address addr="10.0.0.6" addrtype="ipv4"/></host>
<host><status state="up"/><address addr="AA:BB:CC:00:00:07" addrtype="mac"/></host>
<host><status state="up"/><address addr="10.0.0.8" addrtype="ipv4"/><ports><port protocol="tcp" portid="9100"><state state="open"/></port></ports></host>
<runstats><finished elapsed="{elapsed}"/></runstats></nmaprun>"""

hosts = nm._parse_hosts(XML.format(elapsed="1.5"))
assert [h["ip"] for h in hosts] == ["10.0.0.5", "10.0.0.8"], "down hosts and hosts without an address are skipped"
h = hosts[0]
assert h["mac"] == "AA:BB:CC:00:00:05" and h["hostname"] == "nas.local" and h["http_title"] == "My NAS"
assert [p["port"] for p in h["ports"]] == [80, 443, 22], "closed ports are not listed"
assert h["ports"][0] == {"port": 80, "service": "http", "product": "nginx", "version": "1.2", "confirmed": True, "has_http_title": True}
assert h["ports"][1]["confirmed"] is False and h["ports"][1]["has_http_title"] is False
assert h["tls_subject"] and h["tls_issuer"] and h["ssh_hostkey"], h
assert hosts[1]["ports"][0]["service"] is None and "tls_subject" not in hosts[1]
assert nm._parse_hosts("<not xml") == [] and nm._parse_hosts("<nmaprun/>") == []

# labels written in the log
for args, word in ((["x", "broadcast-upnp-info"], "SSDP"), (["broadcast-dhcp-discover"], "DHCP"), (["--top-ports", "1000", "1.1.1.1"], "pilota"),
                   (["broadcast-igmp-discovery"], "IGMP"), (["ssl-cert,ssh-hostkey", "1.1.1.1"], "TLS"), (["--traceroute", "8.8.8.8"], "internet"),
                   (["-sU", "1.1.1.1"], "SNMP"), (["-sV", "1.1.1.1"], "completa"), (["-p", "80", "1.1.1.1"], "porte")):
    assert word in nm._describe_nmap(args), (args, nm._describe_nmap(args))
assert nm._configured_host_timeout(["--host-timeout", "45s", "x"]) == 45.0
assert nm._configured_host_timeout(["x"]) is None and nm._configured_host_timeout(["--host-timeout"]) is None

# a fake nmap process: records the command line, answers with the XML, takes "elapsed" seconds on a fake clock
launched, clock = [], {"t": 0.0, "step": 1.0}


class FakeProc:
    def __init__(self, out):
        self.out, self.killed = out, False

    async def communicate(self):
        clock["t"] += clock["step"]
        if clock.get("hang"):
            await asyncio.sleep(3600)
        return self.out.encode(), b""

    def kill(self):
        self.killed = True

    async def wait(self):
        return 0


answer = {"xml": XML.format(elapsed="1.5")}


async def fake_exec(*cmd, **kw):
    launched.append(cmd)
    proc = FakeProc(answer["xml"])
    launched.append(proc)
    return proc


class FakeTime:
    @staticmethod
    def monotonic():
        return clock["t"]


nm.asyncio.create_subprocess_exec = fake_exec
nm.time = FakeTime
run = lambda c: asyncio.new_event_loop().run_until_complete(c)   # noqa: E731

out = run(nm._run_nmap(["-p", "80", "10.0.0.5"]))
assert launched[0] == ("nmap", "-p", "80", "10.0.0.5", "-oX", "-") and "<nmaprun>" in out

# host-timeout: a scan that lasts about as long as the limit is remembered as incomplete, a quick one clears it
nm.timed_out.clear()
clock["step"] = 44.0
run(nm._run_nmap(["--host-timeout", "45s", "10.0.0.5"]))
assert "10.0.0.5" in nm.timed_out
clock["step"] = 2.0
run(nm._run_nmap(["--host-timeout", "45s", "10.0.0.5"]))
assert "10.0.0.5" not in nm.timed_out

# pilot: fast device not slow; slow by elapsed time; slow because the host-timeout was reached; garbage output is slow by default
clock["step"] = 1.0
answer["xml"] = XML.format(elapsed="1.5")
p = run(nm.pilot("10.0.0.5"))
assert p["slow"] is False and p["elapsed"] == 1.5 and [x["port"] for x in p["ports"]] == [80, 443, 22], p
assert "--top-ports" in launched[-2] and "1000" in launched[-2]
answer["xml"] = XML.format(elapsed="9.0")
assert run(nm.pilot("10.0.0.5"))["slow"] is True
answer["xml"] = XML.format(elapsed="1.5")
clock["step"] = float(nm.PILOT_TIMEOUT_S)
p = run(nm.pilot("10.0.0.5"))
assert p["slow"] is True and "10.0.0.5" not in nm.timed_out, "the pilot does not leave the marker for the pipeline"
answer["xml"] = "garbage"
clock["step"] = 1.0
p = run(nm.pilot("10.0.0.5"))
assert p == {"slow": True, "elapsed": nm.PILOT_TIMEOUT_S, "ports": []} or p["ports"] == []

# fast_ports and tls_ssh_scan
answer["xml"] = XML.format(elapsed="1.5")
fp = run(nm.fast_ports("10.0.0.5", timeout=30))
sv_call = [c for c in launched if isinstance(c, tuple) and "-sV" in c][-1]   # the targeted version scan; a plain connect to the no-talk ports follows it
assert fp["ip"] == "10.0.0.5" and nm.FAST_PORTS in sv_call and "30s" in sv_call and "--exclude-ports" in sv_call
answer["xml"] = "garbage"
assert run(nm.fast_ports("10.0.0.5")) is None
answer["xml"] = XML.format(elapsed="1.5")
ports = [{"port": 80, "service": "http"}, {"port": 22, "service": "ssh"}, {"port": 8443, "service": "x"}, {"port": 9999, "service": "weird-ssl"}]
t = run(nm.tls_ssh_scan("10.0.0.5", ports))
assert set(t) == {"tls_subject", "tls_issuer", "ssh_hostkey"} and "22,8443,9999" in launched[-2], (t, launched[-2])
n = len(launched)
assert run(nm.tls_ssh_scan("10.0.0.5", [{"port": 80, "service": "http"}])) == {} and len(launched) == n, "no TLS/SSH port: nmap is not started"
answer["xml"] = "garbage"
assert run(nm.tls_ssh_scan("10.0.0.5", ports)) == {}

# a cancelled scan kills nmap and lets the cancellation through
async def cancelled():
    clock["hang"] = True
    task = asyncio.ensure_future(nm._run_nmap(["10.0.0.5"]))
    await asyncio.sleep(0.05)
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        return launched[-1].killed
    return None


assert asyncio.new_event_loop().run_until_complete(cancelled()) is True
print("TUTTO OK")
