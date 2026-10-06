"""Opens an encrypted Vedetta report (the .txt attached to an issue) with the maintainer's private key.
    python tools/open_report.py vedetta-report-ab12cd.txt [-k ~/.vedetta/report_private.key] [-o out.zip]
Needs PyNaCl (pip install pynacl). The private key never goes in the repository."""
import argparse
import base64
import sys
from pathlib import Path

BEGIN, END = "-----BEGIN VEDETTA REPORT-----", "-----END VEDETTA REPORT-----"


def open_report(text: str, private_b64: str) -> bytes:
    from nacl.public import PrivateKey, SealedBox
    if BEGIN not in text or END not in text:
        raise ValueError("this is not a Vedetta encrypted report")
    body = text.split(BEGIN, 1)[1].split(END, 1)[0]
    sealed = base64.b64decode("".join(body.split()))
    return SealedBox(PrivateKey(base64.b64decode(private_b64.strip()))).decrypt(sealed)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("file")
    ap.add_argument("-k", "--key", default=str(Path.home() / ".vedetta" / "report_private.key"))
    ap.add_argument("-o", "--out")
    args = ap.parse_args()
    try:
        data = open_report(Path(args.file).read_text(encoding="ascii", errors="strict"), Path(args.key).read_text(encoding="ascii"))
    except Exception as exc:
        print(f"Cannot open the report: {exc}", file=sys.stderr)
        return 1
    out = Path(args.out) if args.out else Path(args.file).with_suffix(".zip")
    out.write_bytes(data)
    print(f"Decrypted: {out} ({len(data)} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
