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
