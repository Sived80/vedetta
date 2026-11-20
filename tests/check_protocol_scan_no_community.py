"""The light UDP search asks NetBIOS only: Vedetta never tries a credential on a device, and the SNMP scripts of nmap
(snmp-sysdescr, snmp-info) try the community "public" on their own. The command must not open UDP 161 nor load any snmp script.
    python tests/check_protocol_scan_no_community.py"""
import asyncio
import os
import sys
import tempfile

os.environ.setdefault("VEDETTA_DATA_DIR", tempfile.mkdtemp())
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app.scan import scan_protocols  # noqa: E402

asked = []


async def fake_run(args, semaphore=None):
    asked.append(list(args))
    return "<nmaprun><host><hostscript><script id='nbstat' output='NetBIOS name: NAS-1, NetBIOS user: x'/></hostscript></host></nmaprun>"


scan_protocols._run_nmap = fake_run
info = asyncio.run(scan_protocols.protocol_scan("10.0.0.5"))
args = asked[0]
joined = " ".join(args)
assert "snmp" not in joined.lower(), args
assert "161" not in args[args.index("-p") + 1].split(","), args
assert args[args.index("--script") + 1] == "nbstat", args
assert info == {"netbios_name": "NAS-1"}, info
print("check_protocol_scan_no_community: ok")
