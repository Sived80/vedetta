"""The language of each Home Assistant user: kept on the server for the user the ingress names (X-Remote-User-ID), so it follows them to
every browser; without a choice the language of Home Assistant is used, then the browser's (Accept-Language), then the default of the app.
A wrong or hostile request cannot break it: an unknown language is refused, a strange id is ignored, the file cannot grow without limit."""
import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from fastapi.testclient import TestClient  # noqa: E402
from app import i18n, main  # noqa: E402
from app.storage import userlang  # noqa: E402

tmp = Path(tempfile.mkdtemp())
userlang.PATH = tmp / "user_lang.json"
userlang._cache = None
os.environ.pop("VEDETTA_LANGUAGE", None)
c = TestClient(main.app)
ALICE = {"X-Remote-User-ID": "a" * 32}
BOB = {"X-Remote-User-ID": "b" * 32}


def page(headers=None, query=""):
    r = c.get("/ha" + query, headers=headers or {})
    assert r.status_code == 200, r.text[:300]
    lang = r.text.split("window.VEDETTA_LANG = ")[1].split(";")[0].strip('" ')
    auto = r.text.split("window.VEDETTA_LANG_AUTO = ")[1].split(";")[0].strip()
    return lang, auto == "true"


# 1) nobody chose, nothing known: English; the browser's language is used when we have it
i18n.set_system_language(None)
assert page() == ("en", True), page()
assert page({"Accept-Language": "it-IT,it;q=0.9,en;q=0.8"}) == ("it", True), "la lingua del browser"
assert page({"Accept-Language": "fr-FR,fr;q=0.9,cs;q=0.5"}) == ("cs", True), "la prima lingua che abbiamo, non la prima in elenco"
assert page({"Accept-Language": "fr-FR,de;q=0.9"}) == ("en", True), "nessuna lingua nostra: inglese"
assert page({"Accept-Language": "it;q=0, cs;q=0.2"}) == ("cs", True), "q=0 vuol dire 'non voglio questa'"
assert page({"Accept-Language": "x" * 5000 + ",it"}) == ("en", True), "un'intestazione enorme non rompe niente"

# 2) the language of Home Assistant comes before the browser's
i18n.set_system_language("cs")
assert page({"Accept-Language": "it"}) == ("cs", True), "la lingua di Home Assistant"
i18n.set_system_language("pt-BR")
assert i18n.system_language() is None, "una lingua che non abbiamo non conta"
i18n.set_system_language("it_IT")
assert i18n.system_language() == "it", "it_IT e it-IT sono 'it'"
i18n.set_system_language("cs")

# 3) the app option decides the default, unless it is `auto`
os.environ["VEDETTA_LANGUAGE"] = "en"
assert page() == ("en", True), "l'opzione dell'app, se non e' auto, vale per tutti"
os.environ["VEDETTA_LANGUAGE"] = "auto"
assert page() == ("cs", True), "auto segue Home Assistant"
os.environ.pop("VEDETTA_LANGUAGE")

# 4) a choice is kept on the server for that user and follows them to a browser with no cookie
r = c.post("/api/lang/it", headers=ALICE)
assert r.status_code == 200 and "lang=it" in r.headers.get("set-cookie", ""), r.text
c.cookies.clear()
assert page(ALICE) == ("it", False), "Alice ritrova la sua scelta anche senza cookie, da un altro browser"
assert page(BOB) == ("cs", True), "Bob non e' toccato: segue Home Assistant"
assert page() == ("cs", True), "chi non ha un utente non e' toccato"
assert json.loads(userlang.PATH.read_text(encoding="utf-8")) == {"a" * 32: "it"}, "scritto sul file, per utente"

# 5) the address overrides, and it counts as a choice
assert page(ALICE, "?lang=en") == ("en", False)
assert page(ALICE, "?lang=zz") == ("it", False), "una lingua sconosciuta nell'indirizzo e' ignorata"

# 6) back to automatic: the saved choice and the cookie go away
r = c.post("/api/lang/auto", headers=ALICE)
assert r.status_code == 200
c.cookies.clear()
assert page(ALICE) == ("cs", True), "tornata automatica: segue Home Assistant"
assert json.loads(userlang.PATH.read_text(encoding="utf-8")) == {}, "la voce e' stata tolta"

# 7) without a user id (direct access, development) the cookie is the memory of the browser
c.post("/api/lang/it")
assert page() == ("it", False), "senza utente vale il cookie"
c.post("/api/lang/auto")
assert page() == ("cs", True)
assert not userlang.PATH.exists() or json.loads(userlang.PATH.read_text(encoding="utf-8")) == {}, "senza utente non si scrive niente sul server"

# 8) refusals and hostile input
assert c.post("/api/lang/zz", headers=ALICE).status_code == 404, "lingua sconosciuta rifiutata"
assert c.post("/api/lang/..%2f..%2fetc", headers=ALICE).status_code in (404, 405), "niente percorsi"
for bad in ("../../x", "a b", "x" * 65, "", "é"):
    assert userlang.put(bad, "it") is False and userlang.get(bad) is None, f"id strano ignorato: {bad!r}"
assert page({"X-Remote-User-ID": "../../etc"}) == ("cs", True), "un id strano non rompe la pagina"
userlang.PATH.write_text("{ non e' json", encoding="utf-8"); userlang._cache = None
assert page(ALICE) == ("cs", True), "un file rovinato non rompe la pagina"
userlang.PATH.write_text(json.dumps({"a" * 32: "xx", "b" * 32: "it", "../x": "it"}), encoding="utf-8"); userlang._cache = None
assert page(ALICE) == ("cs", True) and page(BOB) == ("it", False), "una lingua che non c'e' piu' o un id strano nel file sono ignorati"

# 9) the file does not grow without limit: the oldest choice goes first
userlang._cache = {}
for i in range(userlang.MAX_USERS + 20):
    assert userlang.put(f"u{i}", "it")
data = json.loads(userlang.PATH.read_text(encoding="utf-8"))
assert len(data) == userlang.MAX_USERS and "u0" not in data and f"u{userlang.MAX_USERS + 19}" in data, "il limite regge e toglie le piu' vecchie"
assert userlang.put("u519", "cs") and userlang.get("u519") == "cs", "una scelta cambiata si aggiorna"

print("TUTTO OK")
