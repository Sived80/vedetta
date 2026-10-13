"""Shared by the golden-master export tests: the files the app rewrites itself (for example devices.yaml) use the line ending of the platform
(CRLF on Windows, LF on Linux), so the compared values are made line-ending neutral on both sides."""


def lf(value):
    """The same structure with every CRLF in its strings turned into LF."""
    if isinstance(value, str):
        return value.replace("\r\n", "\n")
    if isinstance(value, list):
        return [lf(x) for x in value]
    if isinstance(value, dict):
        return {k: lf(v) for k, v in value.items()}
    return value


def ignore_file_size(results, name):
    """The manifest lists the size in bytes of every exported file; a file the app rewrites itself has a platform-dependent size (CRLF adds one byte per line), so that one size is left out of the comparison."""
    for scenario in results.values():
        files = (scenario["entries"].get("manifest.json") or {}).get("files", {})
        if name in files:
            files[name] = None


def first_difference(got, want, path=""):
    """Where two JSON-like values first differ, as 'path: got != want' (cut short), or '' when they are equal: for a failure message that says what changed."""
    if isinstance(got, dict) and isinstance(want, dict):
        for key in sorted(set(got) | set(want), key=str):
            if key not in got or key not in want:
                return "%s/%s: only in %s" % (path, key, "want" if key not in got else "got")
            found = first_difference(got[key], want[key], "%s/%s" % (path, key))
            if found:
                return found
        return ""
    if isinstance(got, list) and isinstance(want, list) and len(got) == len(want):
        for i, (a, b) in enumerate(zip(got, want)):
            found = first_difference(a, b, "%s[%d]" % (path, i))
            if found:
                return found
        return ""
    return "" if got == want else "%s: %s != %s" % (path, repr(got)[:160], repr(want)[:160])
