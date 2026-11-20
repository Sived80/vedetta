"""Plural forms (19/11 review): Czech counts 1 / 2-4 / 5+ ("1 nové zařízení", "3 nová zařízení", "5 nových zařízení"); the server picks
«_few» for 2-4 in Czech, the other languages stay with one and other. The page does the same with Intl.PluralRules (check_plural_ui.js)."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app import i18n  # noqa: E402

cs = [i18n.translate("cs", "settings.new_devices", n=n) for n in (1, 3, 5, 22)]
assert cs == ["1 nové zařízení v síti", "3 nová zařízení v síti", "5 nových zařízení v síti", "22 nových zařízení v síti"], cs
assert [i18n.plural_of(n, "cs") for n in (0, 1, 2, 4, 5, 12)] == ["other", "one", "few", "few", "other", "other"]
assert [i18n.plural_of(n, lang) for lang in ("en", "it", "de") for n in (1, 3)] == ["one", "other"] * 3
en = [i18n.translate("en", "settings.new_devices", n=n) for n in (1, 3)]
assert "1 " in en[0] and "3 " in en[1] and en[0] != en[1], en
print("ALL OK")
