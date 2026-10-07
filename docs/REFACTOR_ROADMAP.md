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
- [x] 2. `core.js`: state `S`, `api`, `t`, `esc`, `icon`, `snack`, formatting helpers, menus
- [x] 3. `log.js` (log card) (script; its CSS: step 10)
- [x] 4. `export.js` (export window) (script; its CSS: step 10)
- [x] 5. `new-devices.js` (devices found) (script; its CSS: step 10)
- [x] 6. `deep.js` (deep search, badge, menu) (script; its CSS: step 10)
- [x] 7. `network.js` (network card, live menu) (script; its CSS: step 10)
- [x] 8. `tile.js` (tiles, list/grid views, compact list) (script; its CSS: step 10)
- [x] 9. `more-info.js` (the "More info" dialog, attributes, history chart, flag) (script; its CSS: step 10)
- [ ] 10. CSS: move each block of `90-overrides.css` next to the feature it styles (one file per feature, as for the script), then merge it into the rule it corrects and remove dead rules. Proof: the computed styles of every element in every state of the page must not change (comparison in the browser, old sheet against new one, on the debug app)
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

## Done so far
- Script: `10-core.js`, `20-export.js`, `30-deep.js`, `40-network.js`, `50-tile.js`, `60-new-devices.js`, `70-log.js`, `80-more-info.js`, `90-app.js`.
  The joined `ha.js` is byte for byte the 0.4.5 one (180,118 characters, fingerprint `e338f649`), served by the debug app and identical to the installed app.
- Style: `10-base.css` (the designed sheet, layers reset to motion) and `90-overrides.css` (55 later corrections). Joined: byte for byte the 0.4.5 one (`e9889d08`).

