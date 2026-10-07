# Front-end split roadmap

Goal: split `static/ha/ha.js` (one IIFE, ~3,200 lines) and `static/ha/ha.css` (~1,500 lines, patched in layers) into
feature files, **without changing behaviour**. One step = one local commit, full test suite green (`python tools/run_tests.py`).

Rules
- Move code, do not rewrite it. No behaviour change inside a step.
- How (decided at step 1): the parts live in `app/frontend/ha/js/` and `app/frontend/ha/css/` and the app joins them in the order of
  their names (`app/assets.py`); the page still receives one `/static/ha/ha.js` and one `/static/ha/ha.css`, with a version that
  follows the content. So the parts keep ONE scope and ONE cascade order, and every cut can be proved: the joined file must stay
  byte for byte the same (`python tools/asset_fingerprint.py` against the fingerprint of the installed app). A shared namespace
  between separate scripts would have meant rewriting hundreds of calls: it can come later, file by file, once the split is done.
- After each step: jsdom UI tests green, then try on the debug app; the production app is only read for comparison.
- Nothing is published or pushed without an explicit request.

## Steps
- [x] 0. Baseline: tag the current commit, record the size of `ha.js`/`ha.css`, list the functions per section
- [x] 1. Test loader: `build_page.py` and the jsdom tests load several scripts in order
- [ ] 2. `core.js`: state `S`, `api`, `t`, `esc`, `icon`, `snack`, formatting helpers, menus
- [ ] 3. `log.js` (log card) + its CSS
- [ ] 4. `export.js` (export window) + its CSS
- [ ] 5. `new-devices.js` (devices found) + its CSS
- [ ] 6. `deep.js` (deep search, badge, menu) + its CSS
- [ ] 7. `network.js` (network card, live menu) + its CSS
- [ ] 8. `tile.js` (tiles, list/grid views, compact list) + its CSS
- [ ] 9. `more-info.js` (the "More info" dialog, attributes, history chart, flag) + its CSS
- [ ] 10. CSS: merge the `@layer overrides` patches into the rules they override; remove dead rules
- [ ] 11. Final check: full suite, debug app compared with the production app, sizes recorded, docs updated

## Baseline (version 0.4.5, tag `pre-split-0.4.5`)
`ha.js` 3,226 lines, `ha.css` 1,517 lines (55 `@layer overrides` blocks), `icons.js` 158 lines. Sections of `ha.js` (lines of the baseline) and where each goes:

| Lines | Section | Functions | Goes to |
|---|---|---|---|
| 26-64 | language | 3 | `core.js` |
| 65-258 | utilities | 27 | `core.js` |
| 259-296 | state `S` | 0 | `core.js` |
| 297-453 | toast, ripple, bar | 8 | `core.js` |
| 454-581 | menu | 6 | `core.js` |
| 582-830 | export for analysis | 28 | `export.js` |
| 831-970 | deep search | 11 | `deep.js` |
| 971-1137 | pause, ignored devices, search methods | 8 | `network.js` |
| 1138-1468 | filters, "Network" card | 14 | `network.js` |
| 1469-1747 | tile | 13 | `tile.js` |
| 1748-2046 | new devices | 8 | `new-devices.js` |
| 2047-2206 | log | 7 | `log.js` |
| 2207-2967 | "More info" dialog | 40 | `more-info.js` |
| 2968-3226 | update, real-time stream, startup | 12 | `app.js` (loaded last) |

Order of loading: `icons.js`, `core.js`, the feature files, `app.js`. A feature file only uses what the files before it define; what two features share goes to `core.js`.
