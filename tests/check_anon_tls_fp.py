# SPDX-License-Identifier: GPL-3.0-only — additional terms in NOTICE
"""The TLS certificate fingerprint in the export for analysis (1.0.1): `tls_fp` (64 hex digits, unique to one machine like an SSH key) is masked
as tls-cert-N, the same value always the same placeholder (in any case), in text and in parsed JSON; the final check finds one left readable,
and the repair replaces it. The owner's mapping gives the values back.
    python tests/check_anon_tls_fp.py"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app.export import anonymize  # noqa: E402

FP1, FP2 = "3f" * 32, "0a1b2c3d" * 8
a = anonymize.Anonymizer()
out = a.text(json.dumps({"scan_info": {"tls_fp": FP1, "tls_subject": "commonName=gw.lan"}}) + " other " + FP2 + " again " + FP1.upper())
assert FP1 not in out.lower() and FP2 not in out, out
assert out.count("tls-cert-1") == 2 and "tls-cert-2" in out, out
assert a.data({"tls_fp": FP2, "ports": [{"port": 443, "tls_fp": FP1}]}) == {"tls_fp": "tls-cert-2", "ports": [{"port": 443, "tls_fp": "tls-cert-1"}]}
assert a.mapping()["tls_certs"] == {"tls-cert-1": FP1, "tls-cert-2": FP2}
# not a fingerprint: a shorter or a longer run of hex digits, a hex run inside a word
for keep in ("ab" * 31, "ab" * 33, "x" + "ab" * 32):
    assert a.text(keep) == keep, keep

# the final check: one left readable is found, and repaired
fresh = anonymize.Anonymizer()
leaks = fresh.leak_items('{"tls_fp": "%s"}' % FP1)
assert ("TLS certificate", FP1) in leaks, leaks
text, fixed, rest = fresh.repair('{"tls_fp": "%s"}' % FP1)
assert fixed == 1 and rest == [] and "tls-cert-1" in text, (text, rest)
assert fresh.leak_items(text) == []
print("check_anon_tls_fp: ok")
