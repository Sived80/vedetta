"""Encrypted report: sealed with the public key, opened only with the private one, plain text, never a plain file by mistake."""
import asyncio
import base64
import importlib.util
import os
import sys
import zipfile
import io

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from nacl.public import PrivateKey  # noqa: E402
from app import export, report_crypto, routes_ha  # noqa: E402

spec = importlib.util.spec_from_file_location("open_report", os.path.join(os.path.dirname(__file__), "..", "tools", "open_report.py"))
tool = importlib.util.module_from_spec(spec); spec.loader.exec_module(tool)

# the key published in the repository is a real 32-byte public key
assert len(report_crypto.public_key()) == 32
assert len(report_crypto.fingerprint().replace("-", "")) == 16

# seal / open with a temporary pair
priv = PrivateKey.generate()
buf = io.BytesIO()
with zipfile.ZipFile(buf, "w") as z:
    z.writestr("x.json", '{"ip": "10.0.0.5"}')
raw = buf.getvalue()
sealed = report_crypto.seal(raw, bytes(priv.public_key))
text = sealed.decode("ascii")                                    # plain text, GitHub accepts it as .txt
assert text.startswith("VEDETTA ENCRYPTED REPORT") and report_crypto.BEGIN in text and report_crypto.END in text
assert "10.0.0.5" not in text and b"PK" not in sealed[:200]
assert max(len(l) for l in text.splitlines()) <= 110
assert tool.open_report(text, base64.b64encode(bytes(priv)).decode()) == raw
assert report_crypto.seal(raw, bytes(priv.public_key)) != sealed   # a new random seal every time
# another key cannot open it
try:
    tool.open_report(text, base64.b64encode(bytes(PrivateKey.generate())).decode())
    raise AssertionError("opened with the wrong key")
except AssertionError:
    raise
except Exception:
    pass
try:
    tool.open_report("hello", "AAAA")
    raise AssertionError
except ValueError:
    pass

# the route: encrypted by default, plain only on request, and never plain when encryption is missing
export.build_zip = lambda: raw
r = asyncio.run(routes_ha.api_export())
assert r.media_type == "text/plain" and r.headers["content-disposition"].startswith('attachment; filename="vedetta-report-') and r.body != raw
assert r.headers["content-disposition"].endswith('.txt"')
r = asyncio.run(routes_ha.api_export(plain=True))
assert r.media_type == "application/zip" and r.body == raw and "vedetta-analisi-" in r.headers["content-disposition"]
real_seal = report_crypto.seal
def broken(data, key=None):
    raise report_crypto.CryptoUnavailable("no")
report_crypto.seal = broken
r = asyncio.run(routes_ha.api_export())
assert r.status_code == 501 and r.body != raw and b"PK" not in r.body
report_crypto.seal = real_seal
print("TUTTO OK")
