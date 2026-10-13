"""A nmap that hangs must not hold one of the two slots for ever. Found by the global review: _run_nmap relied only on nmap's own --host-timeout; a nmap that did not return (a stuck child, a
filtered network) kept its slot and the pipeline stopped; after an error that was not a cancellation the process was not killed. Now: an absolute limit (the host timeout plus a grace; a fixed maximum
for the commands without a host timeout), the process killed and waited for on every way out."""
import asyncio
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app.scan import scan_common, scan_nmap  # noqa: E402


class Proc:
    def __init__(self, behaviour):
        self.behaviour, self.killed, self.waited = behaviour, False, False

    async def communicate(self):
        if self.behaviour == "hang":
            await asyncio.sleep(3600)
        if self.behaviour == "error":
            raise ValueError("broken pipe in the test")
        return b"<nmaprun/>", b""

    def kill(self):
        self.killed = True

    async def wait(self):
        self.waited = True


made: list = []


def fake_exec(behaviour):
    async def make(*cmd, **kw):
        p = Proc(behaviour)
        made.append(p)
        return p
    return make


run = lambda c: asyncio.new_event_loop().run_until_complete(c)   # noqa: E731
real = asyncio.create_subprocess_exec
scan_nmap.NMAP_GRACE_S, scan_nmap.NMAP_MAX_S = 0.2, 0.4
try:
    # a hang with a host timeout: returns after about the timeout plus the grace, killed and waited for, the address marked as slow
    asyncio.create_subprocess_exec = fake_exec("hang")
    t0 = time.monotonic()
    out = run(scan_nmap._run_nmap(["-T4", "--host-timeout", "1s", "10.0.0.5"]))
    took = time.monotonic() - t0
    assert out == "" and 1.0 <= took < 3.0, (out, took)
    assert made[-1].killed and made[-1].waited and "10.0.0.5" in scan_common.timed_out
    # a hang in a command without a host timeout (a broadcast script): the fixed maximum
    t0 = time.monotonic()
    assert run(scan_nmap._run_nmap(["--script", "broadcast-upnp-info", "-e", "eth0"])) == "" and time.monotonic() - t0 < 2.0
    assert made[-1].killed and made[-1].waited
    # an error that is not a cancellation: the process is killed and the error goes on
    asyncio.create_subprocess_exec = fake_exec("error")
    try:
        run(scan_nmap._run_nmap(["-T4", "10.0.0.6"]))
        raise AssertionError("the error was swallowed")
    except ValueError:
        pass
    assert made[-1].killed and made[-1].waited
    # a normal run is untouched
    asyncio.create_subprocess_exec = fake_exec("ok")
    assert run(scan_nmap._run_nmap(["-T4", "--host-timeout", "30s", "10.0.0.7"])) == "<nmaprun/>"
    assert not made[-1].killed
finally:
    asyncio.create_subprocess_exec = real
print("TUTTO OK")
