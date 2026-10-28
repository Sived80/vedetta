"""Vedetta, the real code, running in the "vedetta" machine of the virtual LAN with its own empty data folder; read through its web API from the host."""
import json
import os
import subprocess
import tempfile
import time
import urllib.request

from tools.lansim.lan import SUBNET

PORT = 8765
ADDRESS = SUBNET + ".2"
PYTHON = "/opt/vedetta-venv/bin/python"
# What the Home Assistant app passes to the real one: no calls to the internet from the simulator.
ENV = {"VEDETTA_IFACE": "e0", "VEDETTA_INTERNET_PUBLIC_IP": "false", "VEDETTA_INTERNET_PATH": "false", "VEDETTA_INTERNET_MAC_DB": "false", "VEDETTA_LOG_LEVEL": "info"}


class VedettaProcess:
    """`with VedettaProcess(code_dir) as v:` starts the app from `code_dir` (a folder holding `app/`), `v.cards()` lists the cards, leaving the block stops it."""

    def __init__(self, code_dir: str, poll_interval: int = 10) -> None:
        self.code_dir = code_dir
        self.poll_interval = poll_interval
        self.data = tempfile.mkdtemp(prefix="lansim-data-")
        self.proc: subprocess.Popen | None = None

    def __enter__(self) -> "VedettaProcess":
        env = {**os.environ, **ENV, "VEDETTA_DATA_DIR": self.data}
        log = open(os.path.join(self.data, "uvicorn.log"), "wb")
        self.proc = subprocess.Popen(["ip", "netns", "exec", "ls-vedetta", PYTHON, "-m", "uvicorn", "app.main:app", "--host", ADDRESS, "--port", str(PORT),
                                      "--workers", "1", "--log-level", "warning"], cwd=self.code_dir, env=env, stdout=log, stderr=log)
        self._wait_ready()
        self.post("/api/settings", {"poll_interval": self.poll_interval})
        return self

    def __exit__(self, *exc) -> None:
        if self.proc:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=15)
            except subprocess.TimeoutExpired:
                self.proc.kill()

    def _wait_ready(self, timeout: float = 90.0) -> None:
        end = time.time() + timeout
        while time.time() < end:
            try:
                self.get("/api/settings")
                return
            except OSError:
                time.sleep(1)
        raise RuntimeError("Vedetta did not start; see %s/uvicorn.log" % self.data)

    def get(self, path: str):
        with urllib.request.urlopen("http://%s:%d%s" % (ADDRESS, PORT, path), timeout=20) as r:
            return json.loads(r.read())

    def post(self, path: str, body: dict):
        req = urllib.request.Request("http://%s:%d%s" % (ADDRESS, PORT, path), json.dumps(body).encode(), {"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.loads(r.read() or b"null")

    def cards(self) -> list[dict]:
        """The cards as the interface gets them (address, name, where the name comes from, online, mobile)."""
        return self.get("/api/ha/devices")["devices"]

    def rename(self, device_id: str, name: str) -> None:
        """What the user does when they give a card a name by hand."""
        self.post("/api/devices/%s/rename" % device_id, {"name": name})

    def add_found(self) -> list[dict]:
        """What a user does after "search the network": the search, then adding everything it found as cards. Returns the hosts that were added."""
        hosts = self.post("/api/scan/quick", {})
        found = [h for h in hosts if h.get("ip")]
        self.post("/api/devices/add", {"devices": [{"ip": h["ip"], "name": h.get("hostname") or "", "name_source": "dhcp" if h.get("hostname") else None} for h in found]})
        return found

    def wait_cycles(self, n: int = 1) -> None:
        """Waits for n update cycles of Vedetta (the interval is set short, so this takes about n * (interval + the cycle itself))."""
        time.sleep(n * (self.poll_interval + 6))
