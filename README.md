# SKI Calculus on FPGA

A massively-parallel evolutionary substrate that evolves **SKI combinatory-logic
programs entirely in FPGA fabric**: each soft core generates a random well-formed
SKI term, reduces it to weak head normal form via in-place graph reduction in
block RAM, and scores it against a target boolean function — with no host in the
inner loop. Extracted from the Cloud FPGA / Manhattan Reasoning monorepo to be
developed standalone against the published SDK.

> **SDK note.** This targets the **[`manhattan-reasoning-gym`](https://pypi.org/project/manhattan-reasoning-gym/)**
> package (v0.1.2). The clients (`client_*.py`) are adapted to the published SDK
> (`mrg.cloud.App` / `mrg.cloud.RegisterMap`). The scripts under `experiments/`
> still use the *pre-PyPI* `mrg.App(...)` interface and hardcoded monorepo paths,
> and are the remaining thing to migrate.

## Measured results (real ECP5-85 hardware)

| K cores | clock | throughput | vs full Apple M4 (2.42 M/s) |
|--------:|------:|-----------:|:---|
| 16 | 120 MHz | 2.48 M cand/s | 1.02× |
| 32 |  75 MHz | 2.82 M cand/s | 1.16× |
| 50 |  60 MHz | 3.72 M cand/s | 1.54× |

Throughput scales linearly with core count; the design is bit-exact against a
CPU reference (`cpu_baseline.c`). See `GA_ENGINE.md` for the full writeup and
`paper/` for the ALIFE late-breaking-work paper.

## Layout

**GA engine (repo root)**
- `ga_design.py` — the canonical engine (source of truth): `ReducerCore`,
  `EvalCore`, `Generator`, `GACore`, and `GAEngine` (K parallel cores behind one
  Wishbone front-end).
- `ski_ga_fpga.py`, `ski_ga_fpga_k16.py`, `_k32.py`, `_k50.py` — self-contained,
  submission-ready copies of the engine at K = 4 / 16 / 32 / 50 (any K is just
  the `num_cores` default).
- `ski_term.py`, `ski_bool.py`, `ga_ref.py` — SKI term encoding, Church-boolean
  evaluation, and a Python reference model.
- `cpu_baseline.c` — bit-identical single-core CPU baseline (the fairness anchor
  for the CPU-vs-FPGA comparison).
- `GA_ENGINE.md` — architecture + results writeup.

**Single-core reducer** — `design.py` is the standalone SKI WHNF reducer core
(the GA engine's reducer grew out of this). `REDUCER.md` documents it in full:
the calculus, the block-RAM heap encoding, and the reducer's register map.

**Cross-core aggregation.** `GAEngine` reduces total-candidates / best-fitness /
any-busy across the cores with a small **async sequential aggregator** (an FSM
that sweeps the cores one per cycle and republishes a registered snapshot). This
replaced a wide combinational reduction whose Amaranth export was ~O(K²) and
stalled at high K — it's what makes K = 32 / 50 buildable. See `GA_ENGINE.md`.

**`tests/`** — Amaranth sim tests (`sim/`) and pure-Python unit tests (`unit/`).
Run: `pytest tests/` (needs `amaranth` + `pytest`). 51 passing.

**`client_*.py` (repo root)** — SDK clients that program a board and drive the
engine, adapted to the published SDK: `client_sdk.py` (reducer demo),
`client_sdk_ga.py` (GA throughput), `client_k16.py` (K=16 at 120 MHz — the
headline run). Run e.g. `mrg run client_k16.py`.

**`experiments/`** — the measurement tooling behind the results above: clock
sweeps, reproducibility runs, K-scaling builds, matmul bit-exact error-rate, and
the candidate-size difficulty explorer. ⚠️ contain hardcoded paths and pre-PyPI
SDK calls; adapt as needed.

**`paper/`** — the ALIFE LBW paper (`alife-lbw.tex` + `alife-lbw-draft.md`),
the overclocking section (`overclocking_section.tex`), figures, and the figure
generators (`make_figures.py`, `make_fig_overclock.py`).

## Quick start

```bash
python -m venv .venv && . .venv/bin/activate
pip install "amaranth>=0.5" pytest manhattan-reasoning-gym
pytest tests/                 # verify the design in simulation
# then adapt client_*.py to the manhattan-reasoning-gym SDK to run on hardware
```
