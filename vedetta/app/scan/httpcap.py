# SPDX-License-Identifier: GPL-3.0-only — additional terms in NOTICE
"""HTTP answers of the devices on the network, read with a ceiling. A device decides how much it sends: a descriptor, a status page
or a SOAP answer of a few KiB can just as well be megabytes (a broken firmware, a hostile host). Every request Vedetta sends to a
device of the LAN reads at most `limit` bytes of the body, counted after the decompression (the bytes httpx yields are already
decoded), and gives up beyond: the answer is then treated as no answer at all.

The result has the few fields the callers read (status_code, headers, content, text, json()), so it takes the place of an httpx
response where a whole body used to be read."""
import json

DEFAULT_LIMIT = 64 * 1024     # a UPnP descriptor, a Shelly or Tasmota status, a SOAP answer: a few KiB; 64 KiB is far above any of them


class TooLarge(ValueError):
    """The body went past the ceiling. A ValueError, so the callers that already drop a malformed answer drop this one too."""


class Capped:
    def __init__(self, status_code: int, headers, content: bytes, encoding: str | None):
        self.status_code = status_code
        self.headers = headers
        self.content = content
        self._encoding = encoding or "utf-8"

    @property
    def text(self) -> str:
        try:
            return self.content.decode(self._encoding, errors="replace")
        except LookupError:                       # a charset name the device made up
            return self.content.decode("utf-8", errors="replace")

    def json(self):
        return json.loads(self.text)


async def request(client, method: str, url: str, limit: int = DEFAULT_LIMIT, **kwargs) -> Capped:
    """One request, its body read until `limit` bytes; TooLarge beyond (the connection is closed at once)."""
    async with client.stream(method, url, **kwargs) as resp:
        body = await _body(resp, limit, f"{method} {url}")
        return Capped(resp.status_code, resp.headers, body, resp.charset_encoding)


async def _body(resp, limit: int, what: str) -> bytes:
    chunks, size = [], 0
    async for chunk in resp.aiter_bytes():
        size += len(chunk)
        if size > limit:
            raise TooLarge(f"{what}: more than {limit} bytes")
        chunks.append(chunk)
    return b"".join(chunks)


async def get(client, url: str, limit: int = DEFAULT_LIMIT, **kwargs) -> Capped:
    return await request(client, "GET", url, limit, **kwargs)


async def post(client, url: str, limit: int = DEFAULT_LIMIT, **kwargs) -> Capped:
    return await request(client, "POST", url, limit, **kwargs)
