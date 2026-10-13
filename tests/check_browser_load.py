"""The page in a real browser. The checks that run in Node (the boot with a fake page, the names used and not defined) and in jsdom (the interface, with the modules joined into one script) cannot see what only a browser
does with the real modules: it loads each file by its address, and two addresses are two modules (the entry loaded as app.js?v=... and imported as ./app.js was a second copy that started the page too early:
`searchEl` was still undefined). This starts the real app with invented devices (tests/ui/demo_server.py), loads /ha in a headless Chrome or Edge (a throwaway profile, the machine of the person is not touched) and checks that
the four devices are drawn and that nothing was thrown in the console. Skipped where no Chrome or Edge is installed."""
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CANDIDATES = [os.environ.get("CHROME_PATH", ""), shutil.which("google-chrome") or "", shutil.which("chromium") or "", shutil.which("chrome") or "", shutil.which("msedge") or "",
              r"C:\Program Files\Google\Chrome\Application\chrome.exe", r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
              r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe", r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"]
browser = next((c for c in CANDIDATES if c and Path(c).exists()), None)
if not browser:
    print("SKIP: no Chrome or Edge found")
    sys.exit(0)

with socket.socket() as s:
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
server = subprocess.Popen([sys.executable, str(ROOT / "tests" / "ui" / "demo_server.py"), str(port)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
profile = tempfile.mkdtemp(prefix="vedetta-browser-")
try:
    for _ in range(60):
        try:
            urllib.request.urlopen("http://127.0.0.1:%d/ha" % port, timeout=2).read()
            break
        except OSError:
            time.sleep(0.5)
    else:
        raise AssertionError("the demo app did not start")
    # the output goes to files, not to pipes: a browser leaves helper processes that keep a pipe open after the main one is gone, and the test would wait for them
    out_path, err_path = Path(profile) / "dom.html", Path(profile) / "log.txt"
    with open(out_path, "wb") as out, open(err_path, "wb") as err:
        subprocess.run([browser, "--headless=new", "--disable-gpu", "--no-first-run", "--user-data-dir=" + profile + "/p", "--window-size=1280,1000", "--virtual-time-budget=10000",
                        "--enable-logging=stderr", "--v=0", "--dump-dom", "http://127.0.0.1:%d/ha?lang=en" % port], stdout=out, stderr=err, stdin=subprocess.DEVNULL, timeout=90)
    dom, log = out_path.read_text(encoding="utf-8", errors="replace"), err_path.read_text(encoding="utf-8", errors="replace")
    for name in ("Router casa", "Luce cucina", "Telefono", "Stampante studio"):
        assert name in dom, "the device %r is not drawn: the page did not start (dom %d bytes; log: %s)" % (name, len(dom), log[-700:])
    console = [line for line in log.splitlines() if "CONSOLE" in line]
    bad = [line for line in console if "Uncaught" in line or "Failed to load" in line or "TypeError" in line or "ReferenceError" in line or "SyntaxError" in line]
    assert not bad, "the console of the page says:\n" + "\n".join(bad[:5])
finally:
    server.terminate()
    try:
        server.wait(timeout=10)
    except subprocess.TimeoutExpired:
        server.kill()
    shutil.rmtree(profile, ignore_errors=True)
print("TUTTO OK")
