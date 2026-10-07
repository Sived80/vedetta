# Privacy and safety

What stays local, what leaves your network, and how to export data for a bug report without exposing anything personal.

[← Back to the README](../README.md)

- 🏡 Everything runs **inside your network**. Data lives in the app’s own `/data`, included in Home Assistant backups.
- 🌐 The only outbound requests are a periodic update of the MAC-vendor table and the optional public-IP check.
- 🔒 Home Assistant access is **read-only by construction**: only registry reads, no services, no writes.
- 🚪 The ingress panel only accepts the Supervisor. Passwords are never exported.
- 📦 *Export for analysis* (menu) builds a local zip with IPs, MAC addresses and names **masked before the file is created**; it is never sent anywhere. See [Report a mistake](PRIVACY.md#report-a-mistake) just below.

## Report a mistake

Vedetta got a device wrong? Open an issue on GitHub and attach an export, **all in one place**. Menu → *Export for analysis* has two ways to export:

| What you press | What you get | What it is for |
|---|---|---|
| **Encrypted export** (the button) | A `.txt` file that only the author of Vedetta can open | **Attach it to a GitHub issue.** It is safe even if the issue is public. |
| **Plain export** (the arrow next to the button) | A `.zip` that is not encrypted | To read it yourself or hand it over to someone you trust. **Never post it in public.** |

**Both are masked before the file is created**, so nothing personal is in them to start with:

- IP addresses keep only the last number (`10.0.0.x`); MAC addresses keep only the manufacturer prefix, which is what shows the brand.
- Names of devices, areas, DHCP and Bonjour hostnames, and the names Home Assistant knows for your devices become `iPhone-1`, `Thermostat-1`, `Area-2`… Email addresses become `email-1@masked.invalid`. The same value always gets the same placeholder, so the relations stay readable.
- Public addresses are masked too (yours and those of your provider's routers; only well-known public DNS servers stay readable), and every password, token or key found in a file or in a log line is replaced by `***`. Nothing is sent anywhere: you download the file yourself.
- **Safety check:** once the files are masked, Vedetta looks again for anything that is still readable (home network addresses in any spelling, real MACs, names, emails, passwords). If it finds something, **it exports nothing** and tells you.

How it is encrypted: the file is sealed with the public key in [`vedetta/app/data/report_key.pub`](../vedetta/app/data/report_key.pub) (fingerprint `84ba-bfcc-4706-163d`), and only the private key, which never leaves the author’s computer, can open it. The table that says which placeholder is which device stays in your own `/data`. If the encryption is not available in your version, Vedetta tells you and exports nothing: it never falls back to a plain file by mistake. The author opens the file with [`tools/open_report.py`](../tools/open_report.py).
