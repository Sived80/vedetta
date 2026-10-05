// Percorso base (ingress di Home Assistant). L'ingress serve l'app sotto un
// prefisso (/api/hassio_ingress/<token>) ma lo toglie prima di inoltrare: le
// route restano /api/..., solo gli URL che il browser costruisce vanno
// prefissati. Il server inietta window.VEDETTA_BASE (e carica questo file) solo
// se c'e' un prefisso: alla radice non cambia nulla.
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
