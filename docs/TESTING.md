# How Vedetta is tested

Vedetta looks at your home network, so a mistake is a wrong name on a card, or worse, an alarm about a problem that is not there. This page shows how a change is checked before it reaches you, with the numbers of the last release.

[← Back to the README](../README.md)

## The way of a change

<picture><source media="(prefers-color-scheme: dark)" srcset="images/testing-pipeline-dark.svg"><img src="images/testing-pipeline-light.svg" alt="The way of a change: test first, 300+ tests, real networks, virtual LAN, CI, debug at home, release" width="100%"></picture>

- **Test first:** every fix starts as a test that fails.
- **300+ automatic tests** on every change (`python tools/gate.py`).
- **Real networks:** exports shared by users are replayed, old code against new. None is kept in the repository.
- **Virtual LAN:** a small network of routers, phones and plugs with the real Vedetta inside (`tools/lansim`), for what is hard to catch at home.
- **CI on Linux**, then a **debug copy** of Vedetta at home before the release.

## An example: the network doctor of 0.11.0

Before switching the doctor on for everyone, its checks were replayed on every export we had.

<picture><source media="(prefers-color-scheme: dark)" srcset="images/testing-before-after-dark.svg"><img src="images/testing-before-after-light.svg" alt="Exports with at least one finding, of 28: restarts that repeat 27 before, 1 after; devices that drop together 5 before, 0 after; a slower gateway 0 and 0" width="100%"></picture>

| Check | 0.10.0 (before) | 0.11.0 (after) |
|---|---|---|
| Restarts that repeat (H05) | 27 of 28 exports | 1 of 28 |
| Devices that drop together (H06) | 5 of 28 | 0 of 28 |
| A slower gateway (H07) | 0 of 28 | 0 of 28 |

The replay caught a mistake before it reached anyone: almost every "device that restarts again and again" was just a **phone** going to sleep. Phones are now left out.

And the other way round: real faults must still be caught. They were added to real history and played on the virtual LAN.

<picture><source media="(prefers-color-scheme: dark)" srcset="images/testing-detection-dark.svg"><img src="images/testing-detection-light.svg" alt="Time until a fault is raised: 6 devices drop together, 1-2 minutes; gateway 3 ms slower, 10-13 minutes; a device restarts every 10 minutes, 43-44 minutes. Not raised: a sleeping phone, a gateway 2 ms slower" width="100%"></picture>

| Fault added | Raised after |
|---|---|
| 6 devices drop together | 1-2 min |
| The gateway answers 3 ms slower | 10-13 min |
| A device restarts every 10 minutes | 43-44 min |
| A phone whose Wi-Fi sleeps · a gateway 2 ms slower | not raised (on purpose) |

## Run it yourself

| What | Command |
|---|---|
| All the tests | `python tools/gate.py` |
| The doctor on your own exports | `python tools/replay_health_engine.py export.zip` (add `--inject periodic:600:8`, `together:6` or `step:3` for a fault) |
| The virtual LAN (Linux, root) | `python3 tools/lansim/run_scenarios.py --code-dir vedetta --scenario S15` |
| The pictures of this page | `python tools/make_testing_charts.py` |

Found something these tests missed? [Open an issue](https://github.com/Sived80/vedetta/issues/new/choose): it becomes a new test.
