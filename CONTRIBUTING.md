# Contributing to Vedetta

Vedetta learns from real networks, and every network is different. There are three ways to help, from the quickest to the biggest.

## 1. A device is wrong or unknown

This is the most useful contribution: every report becomes a fix or a new recognition rule.

1. Leave Vedetta running for **24 hours (48 is better)** and press the deep search once.
2. Open [the issue form](https://github.com/Sived80/vedetta/issues/new/choose) and attach the **encrypted** export (*Export for analysis → For the developer*). It masks IPs, MACs, names and emails before the file is created.
3. Never attach the plain `.zip`, and never write addresses or real names in the text.

## 2. Teach it a device or a logo

Brands, product signatures and logos live in plain data files. [Development](docs/DEVELOPMENT.md) explains where and how, and the tests tell you at once if something breaks.

## 3. A change to the code

- Keep it small and about one thing.
- Run the whole test suite from the repository root and make sure it ends with `TUTTO OK`:
  ```
  python tools/run_tests.py
  ```
- Texts shown to the user go in the language files (`vedetta/app/locales/<code>/`), never in the code. English is the base; a new language is a new folder ([how](docs/DEVELOPMENT.md#add-a-language)).
- A colour that comes from outside data must stay readable on the light and the dark theme.
- Code, comments, commits and documentation are in English. No personal names, addresses or credentials anywhere in the repository.
- Recognition rules must follow the rule of the project: a clue is weighed by family, doubt is shown as doubt, and the reason can always be shown. See [Recognition](docs/RECOGNITION.md).

## Questions and ideas

Use [Discussions](https://github.com/Sived80/vedetta/discussions) for questions, ideas and to show your network. Use issues for problems that can be fixed.

## Conduct

Everyone taking part follows the [Code of Conduct](CODE_OF_CONDUCT.md). A security problem is reported privately: see [Security](SECURITY.md).
