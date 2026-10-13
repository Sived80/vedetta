"""No word of the keyword rules (data/type_words.json) is already said by a type of the same group (data/device_kinds.json). Both feed the family «words» of a group, which counts the highest value once, so a rule
word that a type says in the same way (substring or whole word) with at least the weight of a rule word adds nothing to the scores: it only tells the same fact twice in the list of clues, and it is a second
place to edit. This is the redundancy anomaly of the verification of rule bases, found by a check instead of by an eye. Not flagged, because they are not copies: a type that only tells the platform (its points go to
the platform, not to the group) and a word that the rules match as a substring while the type matches it as a whole word (they find different texts)."""
import os
import sys
import tempfile

os.environ["VEDETTA_DATA_DIR"] = tempfile.mkdtemp()
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app.ha import ha_type_evidence as E  # noqa: E402
from app.ha import ha_type_text as T  # noqa: E402


def redundant_rule_words(rules: dict, kinds: list, platform: set, w_word: int) -> list:
    """[(group, 'subs' | 'toks', word, type)] of the rule words that a type of the same group says in the same way and with a weight of at least `w_word`."""
    found = []
    for group, rule in rules.items():
        for mode, words in (("subs", rule["subs"]), ("toks", sorted(rule["toks"]))):
            for word in words:
                for kd in kinds:
                    if kd["group"] == group and kd["id"] not in platform and kd["w"] >= w_word and word in kd[mode]:
                        found.append((group, mode, word, kd["id"]))
                        break
    return found


# the detector itself, on small tables: a copy is found, the look-alikes are not
rules = {"media": {"subs": ("smarttv", "television"), "toks": {"tv", "cam", "esp32"}}, "iot": {"subs": (), "toks": {"esp32", "bulb"}}}
kinds = [
    {"id": "tv", "group": "media", "w": 3, "subs": ["television"], "toks": {"tv", "tvs"}},                  # says «television» as a substring and «tv» as a word
    {"id": "camera", "group": "media", "w": 1, "subs": [], "toks": {"cam"}},                               # weight below a rule word: the rule still matters
    {"id": "microcontroller", "group": "iot", "w": 2, "subs": [], "toks": {"esp32"}},                      # a platform type: its points do not go to the group
    {"id": "light", "group": "iot", "w": 2, "subs": [], "toks": {"bulb"}},
]
got = redundant_rule_words(rules, kinds, {"microcontroller"}, 2)
assert sorted(got) == [("iot", "toks", "bulb", "light"), ("media", "subs", "television", "tv"), ("media", "toks", "tv", "tv")], got
assert ("media", "subs", "smarttv", "tv") not in got, "a substring in the rules and nothing in the type: not a copy"
assert not [g for g in got if g[2] in ("cam", "esp32")], "a weak type and a platform type do not make a copy"
# a word that is a substring in the rules and a whole word in the type is not a copy (it finds different texts)
assert not redundant_rule_words({"pc": {"subs": ("laptop",), "toks": set()}}, [{"id": "laptop", "group": "pc", "w": 3, "subs": [], "toks": {"laptop"}}], set(), 2)

# the reason the copies could be taken out: every type that counts for its group weighs at least as much as a rule word, so the type alone gives the group the same points; if a type fell below, the words
# taken out of the rules would matter again and the score would drop without a sound
weak = [kd["id"] for kd in E._kinds() if kd["id"] not in E._PLATFORM_KINDS and kd["w"] < T.W_WORD]
assert not weak, "types lighter than a rule word (%d points): the rule words they used to share would have to come back: %s" % (T.W_WORD, weak)

# the real tables
real = redundant_rule_words(T.rules(), E._kinds(), E._PLATFORM_KINDS, T.W_WORD)
assert not real, "rule words already said by a type of the same group (take them out of data/type_words.json): %s" % [("%s %s" % (g, w)) + " (by %s)" % k for g, _m, w, k in real]
print("TUTTO OK")
