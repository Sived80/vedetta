# Front-end split roadmap

Goal: split `static/ha/ha.js` (one IIFE, ~3,200 lines) and `static/ha/ha.css` (~1,500 lines, patched in layers) into
feature files, **without changing behaviour**. One step = one local commit, full test suite green (`python tools/run_tests.py`).

Rules
- Move code, do not rewrite it. No behaviour change inside a step.
- One shared namespace (`Vedetta`) instead of the IIFE locals; one shared state object `S`.
- Scripts are loaded in order from the template (no bundler), each with its own cache version.
- After each step: jsdom UI tests green, then try on the debug app; the production app is only read for comparison.
- Nothing is published or pushed without an explicit request.

## Steps
- [ ] 0. Baseline: tag the current commit, record the size of `ha.js`/`ha.css`, list the functions per section
- [ ] 1. Test loader: `build_page.py` and the jsdom tests load several scripts in order
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
