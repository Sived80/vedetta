import re

from .i18n import t

MAX_NAME_LEN = 40

# The only technical text to exclude by shape: nmap's placeholder when the
# page has no <title> ("Site doesn't have a title (text/html; ...)"). It is not
# a real title. Everything else is decided with generic rules (below).
_USELESS_TITLE_RE = re.compile(r"^site doesn't have a title", re.IGNORECASE)

# Structural signals in the http-title output: a redirect not followed, or followed
# to a login URL ("Did not follow redirect to http://x/login",
# "Requested resource was /login.html"): the title is that of the login
# page, not of the device. An HTTP error page starts with the code
# (404, 403 Forbidden...): language-independent.
_LOGIN_REDIRECT_RE = re.compile(
    r"(did not follow redirect to|requested resource was)\s+\S*(login|signin|sign-in|logon|auth|session)", re.IGNORECASE)
_HTTP_ERROR_TITLE_RE = re.compile(r"^[1-5]\d\d\b")

# (Normalized) titles that appear on 2+ devices: if the same title is
# on different hosts it identifies none of them ("Login", "Index of /", "Welcome
# to nginx!"...). Recomputed from the configuration on every cycle.
_generic_titles: set[str] = set()


def normalize_title(title: str | None) -> str:
    """First line only (nmap adds lines like 'Requested resource was ...'),
    lowercase, whitespace collapsed."""
    if not title:
        return ""
    first = title.strip().splitlines()[0] if title.strip() else ""
    return " ".join(first.split()).lower()


def update_generic_titles(devices: list[dict]) -> None:
    """Compute the titles shared by 2+ devices (scan_info.http_title)."""
    global _generic_titles
    seen: dict[str, int] = {}
    for d in devices:
        t = normalize_title(((d.get("scan_info") or {}).get("http_title")))
        if t:
            seen[t] = seen.get(t, 0) + 1
    _generic_titles = {t for t, n in seen.items() if n >= 2}


def is_useless_title(title: str | None) -> bool:
    """nmap technical placeholder (not a real title)."""
    return bool(title) and bool(_USELESS_TITLE_RE.match(" ".join(title.split())))


def should_show_title(title: str | None) -> bool:
    """True only if the title really identifies the device."""
    if not title or is_useless_title(title):
        return False
    if _LOGIN_REDIRECT_RE.search(title):
        return False
    norm = normalize_title(title)
    if not norm or _HTTP_ERROR_TITLE_RE.match(norm):
        return False
    return norm not in _generic_titles


def truncate_name(name: str | None) -> str | None:
    """Some sources (mDNS first and foremost) sometimes return very long
    technical labels (e.g. DNS-SD names with undecoded escapes): a
    generous but fixed limit keeps them from breaking the card layout."""
    if not name or len(name) <= MAX_NAME_LEN:
        return name
    return name[: MAX_NAME_LEN - 1].rstrip() + "…"


def quantize_uptime(seconds) -> int | None:
    """Whole seconds below a minute, then full minutes: the uptime held in the
    device dictionary changes at most once a minute, so the
    card is not replaced on every cycle."""
    if seconds is None:
        return None
    seconds = int(seconds)
    return seconds if seconds < 60 else seconds // 60 * 60


# Qualities are neutral codes ("excellent"...): the text is chosen at
# display time (key signal.<code>), so the state shared among
# browsers does not depend on anyone's language.
def wifi_quality(rssi) -> tuple[str, str] | tuple[None, None]:
    if rssi is None:
        return None, None
    if rssi >= -50:
        return "excellent", "green"
    if rssi >= -60:
        return "good", "green"
    if rssi >= -70:
        return "fair", "yellow"
    return "weak", "red"


def lan_quality(mbps) -> tuple[str, str] | tuple[None, None]:
    if mbps is None:
        return None, None
    if mbps >= 1000:
        return "excellent", "green"
    if mbps >= 100:
        return "good", "yellow"
    return "weak", "red"
