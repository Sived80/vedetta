# SPDX-License-Identifier: GPL-3.0-only — additional terms in NOTICE
"""`vedetta-passwd`: sets the password of the page from the host, the way to reset a forgotten one (Docker mode).

    docker exec -it vedetta vedetta-passwd            asks it twice, without showing it
    docker exec -i vedetta vedetta-passwd --stdin     reads it from the standard input (scripts, Compose secrets)

The new password closes every open session (the running app sees the change at its next request). Nothing is printed but the outcome:
never the password nor its hash."""
import argparse
import getpass
import sys

from . import passwords, store

TEXTS = {
    "too_short": "The password needs at least %d characters." % passwords.MIN_LENGTH,
    "too_long": "The password can have at most %d characters." % passwords.MAX_LENGTH,
    "too_common": "This password is too easy to guess: choose another one.",
    "mismatch": "The two passwords are different.",
}


def _read(from_stdin: bool) -> tuple[str, str]:
    if from_stdin:
        value = sys.stdin.readline().rstrip("\r\n")
        return value, value
    return getpass.getpass("New password: "), getpass.getpass("Repeat it: ")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="vedetta-passwd", description="Set the password of the Vedetta page (Docker mode).")
    parser.add_argument("--stdin", action="store_true", help="read the password from the standard input (one line)")
    args = parser.parse_args(argv)
    try:
        password, again = _read(args.stdin)
    except (EOFError, KeyboardInterrupt):
        print("Cancelled: the password did not change.", file=sys.stderr)
        return 1
    problem = passwords.problem(password) or (None if password == again else "mismatch")
    if problem:
        print(TEXTS[problem] + " The password did not change.", file=sys.stderr)
        return 1
    store.set_password_hash(passwords.hash_password(password))
    print("Password set. Every open session was closed: sign in again on the page.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
