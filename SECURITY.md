# Security

Found a security problem in Vedetta? Please **do not open a public issue**.

Report it privately: GitHub → **Security** tab → **Report a vulnerability**.

Useful to include: the version, what you did, what happened, and what you expected. Never attach real exports, passwords or tokens.

A normal bug, such as a device recognised wrongly, is not a security problem: use the [issue form](https://github.com/Sived80/vedetta/issues/new/choose).

## How the code reaches you

Vedetta is made by one person, so the checks are automatic and public:

- **`main` is protected.** A change gets in only when the tests pass, the owner included; history cannot be rewritten and release tags cannot be moved or deleted.
- **Every change is tested** on GitHub before it reaches `main` ([Tests](https://github.com/Sived80/vedetta/actions/workflows/tests.yml)).
- **The code is scanned** by GitHub CodeQL for security mistakes, at every change and every week.
- **Dependencies are watched** by Dependabot; an update goes through the same tests and only ships inside a release.
- **An outside score:** [OpenSSF Scorecard](https://scorecard.dev/viewer/?uri=github.com/Sived80/vedetta), updated every week.
- **Home Assistant updates the app only when the version changes**, and every version is in the [changelog](vedetta/CHANGELOG.md).

What the app may do on your network, and why, is in [DOCS.md](vedetta/DOCS.md#permissions-and-what-each-one-is-for) (permissions) and [PRIVACY.md](docs/PRIVACY.md).
