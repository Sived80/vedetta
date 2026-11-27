# SPDX-License-Identifier: GPL-3.0-only — additional terms in NOTICE
"""The login of Vedetta when it runs as a container of its own (Docker): one person, the owner, with a password. Under the Supervisor
Home Assistant logs the person in (ingress) and none of this is used.

- passwords: the password rules and its hash (scrypt, standard library only);
- store: the hash and the sessions on disk (/data/auth.json, /data/sessions.json: only digests, never a password or a session id);
- throttle: the wait after wrong attempts (growing, never a permanent lock);
- setup: the one-time code of the first start, printed in the log of the container."""
