# Privacy and safety

What stays local, what leaves your network, and how to export data for a bug report without exposing anything personal.

[← Back to the README](../README.md)

- 🏡 Everything runs **inside your network**. Data lives in the app’s own `/data`, included in Home Assistant backups.
- 🌐 The only outbound requests are a periodic update of the MAC-vendor table and the optional public-IP check.
- ⭐ Once, after a few days, a small star on the menu invites you to star the project. It is only a link to the project page on GitHub, opened by you with a click; the app sends nothing when it is shown, closed or ignored. It can be switched off with the `star_hint` option.
- 🌍 The language you pick in the menu is remembered on the server for your Home Assistant user, so it follows you to every browser. The only thing stored is an anonymous code of your Home Assistant user next to the language, in `/data`; it never leaves your installation and is not in any export.
- 🔒 Home Assistant access is **read-only by construction**: only registry reads, no services, no writes.
- 🚪 The ingress panel only accepts the Supervisor. Passwords are never exported.
- 📦 *Export for analysis* (menu) builds a file on your own machine and never sends it anywhere. **For the developer** it is masked before it is created and encrypted; **for you** it is your own data, as it is. See [Report a mistake](PRIVACY.md#report-a-mistake) just below.

## Report a mistake

Vedetta got a device wrong? Open an issue on GitHub and attach an export, **all in one place**. Menu → *Export for analysis* first asks **who the export is for**:

| You choose | What you get | What it is for |
|---|---|---|
| **For the developer** | A `.txt` file, **masked and encrypted**: only the author of Vedetta can open it. Up to 20 MB. | **Attach it to a GitHub issue.** It is safe even if the issue is public. |
| **For me** | A `.zip` that is **not masked and not encrypted**: your data as it is, with no size limit | To read it yourself or hand it over to someone you trust. **Never post it in public.** |

Then you choose **which days** to include: tap the first and the last day on the columns (each column is a day, and its height is how much was recorded), move the chart back in time with *Before* and *After* (up to 90 days), or use the buttons *2 days*, *7 days*, *20 days* and *All*. The minimum is 2 days (the deep search runs at 03:00, so one night alone is rarely enough to see what happened) and the maximum 20; *All* is the whole history. A short event from 5 days ago needs only those days, not everything.

**For the developer, everything is masked before the file is created**, so nothing personal is in it to start with:

- IP addresses keep only the last number (`10.0.0.x`); MAC addresses keep only the manufacturer prefix, which is what shows the brand.
- Names of devices, areas, DHCP and Bonjour hostnames, and the names Home Assistant knows for your devices become `iPhone-1`, `Thermostat-1`, `Area-2`… Email addresses become `email-1@masked.invalid`. The same value always gets the same placeholder, so the relations stay readable.
- Public addresses are masked too (yours and those of your provider's routers; only well-known public DNS servers stay readable), and every password, token or key found in a file or in a log line is replaced by `***`. Nothing is sent anywhere: you download the file yourself.
- **Safety check:** once the files are masked, Vedetta looks again for anything that is still readable (home network addresses in any spelling, real MACs, names, emails, passwords). What it finds it **replaces by itself** with placeholders. If something cannot be replaced, the window lists the values (up to 10, only to you: they are never written to a log or to the file) and for each one you choose **Remove** (it is taken out of the export only, not out of the system) or **Keep**. There is no way around it: the file is created after you have decided.

For *For me* there is no masking and no check: only the fields that look like a credential (a password, a token, a key) are still replaced, so a file handed over by mistake does not carry them.

**Flag the device you are reporting.** Open the device sheet and press *Flag this device*, optionally with a short note ("turns on by itself at 3 am"). The export then has a section with that device's card, the reasons behind its name, brand and type, its last 14 days of history and your note, so the report says where to look. Up to 5 devices. The note is masked like the rest (a word that belongs to a device name is replaced too), but **do not write personal data in it**.

How it is encrypted: the file is sealed with the public key in [`vedetta/app/data/report_key.pub`](../vedetta/app/data/report_key.pub) (fingerprint `84ba-bfcc-4706-163d`), and only the private key, which never leaves the author’s computer, can open it. The table that says which placeholder is which device stays in your own `/data`. If the encryption is not available in your version, Vedetta tells you and exports nothing: it never falls back to a plain file by mistake. The author opens the file with [`tools/open_report.py`](../tools/open_report.py).
