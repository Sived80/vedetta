// Base path (Home Assistant ingress). Ingress serves the app under a
// prefix (/api/hassio_ingress/<token>) but strips it before forwarding: the
// routes stay /api/..., only the URLs the browser builds must be
// prefixed. The server injects window.VEDETTA_BASE (and loads this file) only
// if there is a prefix: at the root nothing changes.
(function () {
  var BASE = window.VEDETTA_BASE || "";
  if (!BASE) return;

  function prefixed(url) {
    return typeof url === "string" && url.charAt(0) === "/" && url.charAt(1) !== "/" ? BASE + url : url;
  }

  var nativeFetch = window.fetch;
  if (nativeFetch) {
    window.fetch = function (input, init) {
      return nativeFetch.call(this, prefixed(input), init);
    };
  }

  var NativeEventSource = window.EventSource;
  if (NativeEventSource) {
    var Wrapped = function (url, config) {
      return new NativeEventSource(prefixed(url), config);
    };
    Wrapped.prototype = NativeEventSource.prototype;
    Wrapped.CONNECTING = NativeEventSource.CONNECTING;
    Wrapped.OPEN = NativeEventSource.OPEN;
    Wrapped.CLOSED = NativeEventSource.CLOSED;
    window.EventSource = Wrapped;
  }
})();
