# How Vedetta is tested

Vedetta looks at your home network, so a mistake is a wrong name on a card, or worse, an alarm about a problem that is not there. This page shows how a change is checked before it reaches you, with the numbers of the last release.

[← Back to the README](../README.md)

<picture><source media="(prefers-color-scheme: dark)" srcset="images/testing-numbers-dark.svg"><img src="images/testing-numbers-light.svg" alt="300+ automatic tests, 4,000+ hours of real home networks, 150+ real devices, 14 network scenarios" width="100%"></picture>

## The way of a change

<picture><source media="(prefers-color-scheme: dark)" srcset="images/testing-pipeline-dark.svg"><img src="images/testing-pipeline-light.svg" alt="The way of a change: test first, 300+ tests, real networks, virtual LAN, CI, debug at home, release" width="100%"></picture>

### The virtual LAN, by problem

<picture><source media="(prefers-color-scheme: dark)" srcset="images/testing-scenarios-dark.svg"><img src="images/testing-scenarios-light.svg" alt="Scenarios of the virtual LAN: doubled phone cards 5, names taken from another device 4, a camera hidden from the scan 1, the network doctor 4" width="100%"></picture>

## An example: the network doctor of 0.11.0

Before switching the doctor on for everyone, its checks were replayed on every export we had.

<picture><source media="(prefers-color-scheme: dark)" srcset="images/testing-before-after-dark.svg"><img src="images/testing-before-after-light.svg" alt="Exports with at least one finding, of 28: restarts that repeat 27 before, 1 after; devices that drop together 5 before, 0 after; a slower gateway 0 and 0" width="100%"></picture>

The replay caught a mistake before it reached anyone: almost every "device that restarts again and again" was just a **phone** going to sleep. Phones are now left out.

And the other way round: real faults must still be caught. They were added to real history and played on the virtual LAN.

<picture><source media="(prefers-color-scheme: dark)" srcset="images/testing-detection-dark.svg"><img src="images/testing-detection-light.svg" alt="Time until a fault is raised: 6 devices drop together, 1-2 minutes; gateway 3 ms slower, 10-13 minutes; a device restarts every 10 minutes, 43-44 minutes. Not raised: a sleeping phone, a gateway 2 ms slower" width="100%"></picture>

Run it yourself: `python tools/gate.py` · `python tools/replay_health_engine.py export.zip` · `python3 tools/lansim/run_campaign.py --out results.jsonl`

Found something these tests missed? [Open an issue](https://github.com/Sived80/vedetta/issues/new/choose): it becomes a new test.
