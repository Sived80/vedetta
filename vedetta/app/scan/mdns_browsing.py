"""The DNS-SD browsing shared by the search (scan_mdns) and by the continuous listener (mdns_listener): a browser that asks for the service types, one for every type seen, and the reading
(SRV, TXT, A) of every instance that is announced. What differs is given by the caller: where a reading goes, how long the request of one instance may take, until when new types are accepted."""
import asyncio
import contextlib
import time
from typing import NamedTuple

from . import mdns_parse


class _Zeroconf(NamedTuple):
    """The pieces of zeroconf that the browsing uses, imported and created together (zeroconf may be missing): the object, the classes of the browser and of the service info, IPv4 only, the "removed" state."""
    azc: object
    browser: type
    info: type
    v4: object
    removed: object


class Browsing:
    def __init__(self, zc: _Zeroconf, on_found, info_timeout: int, types_window: float | None):
        self.zc, self._on_found, self._info_timeout, self._types_window = zc, on_found, info_timeout, types_window
        self._t0 = time.monotonic()
        self.browsers: list = []
        self.types: set[str] = set()
        self.tasks: set[asyncio.Task] = set()

    @classmethod
    def open(cls, on_found, info_timeout: int, types_window: float | None = None):
        """`on_found((type without .local., instance, address, txt))` is called for every IPv4 address of an instance; `types_window` (seconds) closes the acceptance of new types."""
        from zeroconf import IPVersion, ServiceStateChange  # late: zeroconf may be missing
        from zeroconf.asyncio import AsyncServiceBrowser, AsyncServiceInfo, AsyncZeroconf

        azc = AsyncZeroconf(ip_version=IPVersion.V4Only)
        return cls(_Zeroconf(azc, AsyncServiceBrowser, AsyncServiceInfo, IPVersion.V4Only, ServiceStateChange.Removed), on_found, info_timeout, types_window)

    def start(self) -> None:
        self.browsers.append(self.zc.browser(self.zc.azc.zeroconf, mdns_parse._MDNS_META_TYPE, handlers=[self.on_type]))

    def on_type(self, zeroconf, service_type, name, state_change) -> None:
        # for the meta-query `name` is the announced service type (e.g. _hap._tcp.local.)
        if state_change is self.zc.removed or name in self.types:
            return
        if self._types_window is not None and time.monotonic() - self._t0 > self._types_window:
            return
        self.types.add(name)
        self.browsers.append(self.zc.browser(self.zc.azc.zeroconf, name, handlers=[self.on_instance]))

    def on_instance(self, zeroconf, service_type, name, state_change) -> None:
        if state_change is self.zc.removed:
            return
        task = asyncio.ensure_future(self.read_instance(service_type, name))
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)

    async def read_instance(self, stype: str, name: str) -> None:
        info = self.zc.info(stype, name)
        try:
            if not await info.async_request(self.zc.azc.zeroconf, self._info_timeout):
                return
        except Exception:
            return
        suffix = "." + stype
        instance = name.removesuffix(suffix)
        txt = mdns_parse._props_to_txt(info.properties)
        short = stype.removesuffix(".local.")
        for address in info.parsed_addresses(self.zc.v4):
            self._on_found((short, instance, address, txt))

    async def close(self) -> None:
        for browser in self.browsers:
            with contextlib.suppress(Exception):
                await browser.async_cancel()
        for task in list(self.tasks):
            task.cancel()
        with contextlib.suppress(Exception):
            await self.zc.azc.async_close()
