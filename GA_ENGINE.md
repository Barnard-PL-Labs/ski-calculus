# SKI genetic-algorithm engine — massively parallel circuit evolution on FPGA

A fully on-chip genetic algorithm that evolves SKI-combinator terms toward a
target boolean function (truth table). The motivating idea: SKI reduction is a
near-ideal FPGA workload — tiny soft cores, BRAM-cheap, embarrassingly parallel
— so many evaluators packed onto one device can match a sizable CPU farm's
candidate-evaluation throughput at a fraction of the power and cost.

This is the hardware companion to the `ski_calculus` WHNF reducer. Where that
example reduces one host-supplied term, this engine **generates, evaluates, and
selects candidates entirely in fabric**, with the host only seeding the target
and draining counters.

## Architecture (bottom-up, all in `ga_design.py`)

| Component | Role |
|---|---|
| `ReducerCore` | WHNF graph reducer over an external heap; exposes the WHNF head tag |
| `EvalCore` | Owns template + work heaps + a `ReducerCore`. Scores a candidate against a target truth table: for each of 2ⁿ rows it builds `cand b₁…bₙ T F` in scratch, reduces, and classifies the head as `T`/`F`, accumulating matched bits |
| `Generator` | LFSR-driven random **pure-SKI** candidate generator. Every app node references only earlier candidate nodes (acyclic, in-range pointers — well-formed by construction) |
| `GACore` | `Generator` + `EvalCore` + counter + best-tracker. Free-running: generate → evaluate → update best → count → repeat |
| `GAEngine` | K parallel `GACore`s behind one Wishbone front-end. Host sets target/seed/go and reads total candidates + global best |

### Boolean encoding

Church booleans: `TRUE = K`, `FALSE = K I`. A candidate's output is read by
applying it to two inert sentinel atoms: `cand b₁…bₙ T F` reduces to `T` or `F`.
The node format carries two extra tags (`T=4`, `F=5`) for these atoms. Anything
that doesn't resolve to `T`/`F` (diverges past `MAX_STEPS`, overflows, or is
malformed) scores as a miss — so divergent garbage is selected against.

### Why it parallelizes perfectly

Each `GACore` is independent: its own heaps, its own LFSR (seeded distinctly per
core for search diversity), its own loop. There is **no host traffic in the
inner loop** — the wall we measured earlier (every Wishbone op = an HTTP/JTAG
round-trip) is gone. The host writes the target once and reads a counter at the
end. Throughput scales with the number of cores until the fabric is full.

## Verification (all in sim, against the S1 Python reference)

- `tests/unit/test_bool.py` — Church-boolean eval + truth-table fitness + the
  reference GA (the CPU baseline).
- `tests/sim/test_evaluator.py` — hardware fitness == reference fitness (S2).
- `tests/sim/test_generator.py` — generated candidates are well-formed pure-SKI
  terms, vary with seed, and parse/score cleanly.
- `tests/sim/test_ga_engine.py` — full loop liveness, parallel counting, best
  tracking, and a cycles/candidate probe.

## Throughput model

```
candidates/sec  =  K · f_clk / C_candidate
```

- `K` — parallel cores (resource-bound; BRAM is the binding constraint: each
  core's template+work heaps are ~1 EBR).
- `f_clk` — 50 MHz SoC clock.
- `C_candidate` — cycles per candidate = (generation) + 2ⁿ · (reduction). The
  current re-unwind reducer is the conservative case; a persistent-spine-stack
  reducer (~2–4 cyc/step) is the obvious next optimization.

## S4 — resource utilization (measured by local synthesis)

`yosys synth_ecp5` on the exported engine (cell counts scale cleanly linearly,
confirming independent cores):

| K  | LUT4   | carry (CCU2C) | FF (TRELLIS_FF) | BRAM (DP16KD) | DSP (MULT18) |
|---:|-------:|--------------:|----------------:|--------------:|-------------:|
| 4  | 3,595  | 656           | 2,003           | 4             | 8            |
| 8  | 7,279  | 1,320         | 3,915           | 8             | 16           |
| 16 | 14,365 | 2,646         | 7,739           | 16            | 32           |

**Per core:** ≈1,250 LUT-equivalents, **1 BRAM (EBR)**, **2 DSP**, ~485 FFs.

Against the ECP5-85 (`LFE5UM5G-85F`: ~83,640 LUT4, 208 × 18 Kbit EBR, 156 DSP),
the binding constraint is **LUTs**:

| Resource | Budget (after SoC) | Per core | Max K |
|---|---:|---:|---:|
| **LUT4** | ~77,000 | ~1,250 | **~60** ← binds |
| DSP | 156 | 2 | ~78 |
| BRAM (EBR) | ~185 | 1 | ~185 |
| FF | ~77,000 | ~485 | ~158 |

So **~60 cores fit on one ECP5-85.** (The 2 DSP/core come from the generator's
bounded-index multiplies; swapping them for a mask scheme would free the DSPs,
but LUTs bind first either way.) Empirically, **K=16 builds and routes on the
real board** (the remote `build_and_program` completed in ~13 min) — P&R time,
not fabric, is what grows uncomfortable at high K (K=16 already exceeds the
SDK's 600 s client-poll budget; the build itself still finishes server-side).

## S6 — measured throughput (real hardware)

Measured on `fpga0` (ECP5-85, 50 MHz), evolving **XOR** (`n=2`, table
`[0,1,1,0]`), `cand_size=16`, `max_steps=2000`, 5.7 s free-running window:

| K cores | candidates evaluated | window | throughput | per core | best |
|--------:|---------------------:|-------:|-----------:|---------:|:----:|
| **4**  | 1,377,135 | 5.70 s | **241,670 cand/s**   | 60,417 cand/s | **4/4 (SOLVED)** |
| **8**  | 2,641,271 | 5.16 s | **512,152 cand/s**   | 64,019 cand/s | **4/4 (SOLVED)** |
| **16** | 5,812,869 | 5.69 s | **1,021,698 cand/s** | 63,856 cand/s | **4/4 (SOLVED)** |

Three measured points, **textbook linear scaling**: 4→16 cores (4×) gives 4.23×
throughput, per-core rate dead flat at ~63k cand/s. The cores share nothing in
the inner loop, so throughput just tracks core count. Per-core counts stay
balanced (e.g. K=16 spreads ~210k–557k across all 16 cores) — real parallel
work, not one core carrying the rest. (K=16 P&R takes ~15 min, well past the
SDK's default 600 s client-poll budget; `client_k16.py` extends the poll so the
client stays attached through the build.)

**Projection to a full chip.** Per-core rate holds at ~63,900 cand/s across 4/8/16
cores and the engine is LUT-bound at ~60 cores (S4), so a full ECP5-85 projects to
**~3.8 M candidates/sec** — on a ~$40, ~2–5 W part. A modern datacenter FPGA
(10–100× this fabric) would project to 10⁷–10⁸ cand/s/card.

### Against the CPU baseline

The pure-Python reference GA (`ski_bool.evolve`, the S1 baseline) runs at
~10³ candidate-evaluations/sec on one core and **stalled at 3/4 on XOR** in a
60 s run. The 4-core FPGA engine evaluated **1.38 M candidates and solved XOR
(4/4) in under 6 seconds** — ~90× the pure-Python rate while actually finding
the solution, using a small fraction of a ~$40, ~2–5 W ECP5.

Honest framing for the "100k CPUs" comparison: one fast *compiled* CPU core
(not Python) doing SKI reduction is roughly in the 10⁴–10⁵ candidate/sec range,
so 4 of these small soft cores ≈ one CPU core in raw throughput. The FPGA story
is **density and efficiency**, not beating a CPU core one-to-one:

- this is 4 cores on a *fraction* of a small, old ECP5 (see S4 for how many fit);
- candidates/sec **per watt** and **per dollar** are ~10²–10³× a CPU's;
- a modern datacenter FPGA has 10–100× this ECP5's fabric → 10⁷–10⁸ cand/s/card,
  genuinely farm-competitive — and the architecture (on-chip generate→evaluate→
  select, zero host traffic in the loop) is exactly what transfers.

The point isn't "one ECP5 beats 100k CPUs" — it's "the same search runs at a
tiny fraction of the silicon, power, and cost, and scales with the fabric."

## CPU comparison (measured, identical workload)

A C port of the *exact* workload (same generation, same re-unwind WHNF reducer,
same XOR eval, same `MAX_STEPS`; `-O3`) benchmarked on this machine — an Apple
**M4** (3 nm, 2024, ~4.4 GHz). Same algorithm both sides, so it's apples-to-apples.

| Platform | per core | full chip | power | process |
|---|---:|---:|---:|---:|
| Apple M4 (4P+6E) | ~320k/s (isolated) | **2.42 M/s** (measured) | ~22 W | 3 nm '24 |
| ECP5-85 soft core | 63,856/s (@50 MHz) | **3.8 M/s** (~60 cores, proj.) / 1.02 M/s (16, measured) | ~3 W | 28 nm '14 |

Two facts that look contradictory but aren't:

- **Per core, the CPU wins ~5×** (320k vs 64k) — purely clock. The M4 runs ~88×
  the ECP5 SoC's 50 MHz.
- **Per cycle, the FPGA core is ~18× more efficient**: ~780 cycles/candidate vs
  ~14,000 on the M4 (no instruction fetch/decode, no cache misses — the datapath
  *is* the reducer). The CPU only wins per-core because 88× clock ÷ 18× cycles ≈ 5×.

So **one 28 nm, ~$40, ~3 W FPGA matches a 3 nm flagship CPU's whole-chip
throughput** on this workload — and beats it **~12× per watt** (1.3 M vs 0.11 M
cand/s/W). Process-normalized (same node), the architectural gap is far larger.
And the FPGA reducer here is the *unoptimized* re-unwind design; the spine-stack
reducer (S3) cuts ~780 cyc/candidate by 3–10×, multiplying every FPGA number.

### Datacenter-scale projection (assumptions stated)

A datacenter FPGA (e.g. Alveo U250 / VU13P, 16 nm) has ~1.73 M LUTs (~20× this
ECP5) and clocks soft logic at ~300 MHz (~6× the 50 MHz SoC):

- ~1,200 cores/card (LUT-bound) × ~380k/s (63.9k × 6 for clock) ≈ **~460 M cand/s/card** (~225 W).
- That's ~120× one ECP5-85, ~190× a full M4.

Versus a **100k-CPU farm** (the CPU-SKI approach at scale): at ~200k/s per server
core, ~**2×10¹⁰ cand/s**. Matching that takes **~45 FPGA cards** — roughly:

| | 100k CPU cores | ~45 FPGA cards | ratio |
|---|---:|---:|---:|
| hardware | ~1,500–3,000 servers | ~6 host servers + 45 cards | |
| power | ~1–1.5 MW | ~12–15 kW | **~80× less** |
| capex | ~$15–40 M | ~$0.5 M | **~40–80× less** |

**Caveats (honest):** (1) the FPGA reducer is unoptimized — S3 widens the gap;
the CPU C code is also straightforward and a SIMD/JIT version might claw back
2–5×, so both sides have headroom. (2) This favors *many small candidates*
(cand_size 16, n=2, short reductions) — exactly the SKI-evolution regime; very
large terms need bigger heaps (fewer cores) and tilt back toward CPUs. (3) The
datacenter clock/LUT scaling is projected, not measured. (4) This engine does
independent random search + best-tracking per core; a full GA with crossover
across a shared population adds some inter-core coordination. The order-of-
magnitude conclusion — **~1–2 orders of magnitude less power and cost than a
CPU farm for equal throughput** — is robust to these.

## Future work — from combinator programs to evolvable circuits

The reusable asset is the **engine** (generate → evaluate-on-fabric → select,
massively parallel, no host in the loop), not the SKI substrate. The genome can
be swapped:

- **Virtual reconfigurable circuit (VRC).** Replace the SKI heap with a config
  vector for a soft, runtime-programmable LUT/gate array (CGP-style). Candidates
  load in microseconds (no resynthesis) and are evaluated as *real* circuit
  behavior on fabric, so fitness can include actual latency / switching activity
  / active-cell count. This turns the throughput result into a substrate for
  **intrinsic evolvable hardware** at evaluation rates that make previously
  infeasible searches affordable.
- **ML-relevant primitives + quality-diversity.** ML's approximation tolerance
  smooths the landscape and opens a rich space (approximate MACs, stochastic
  compute, systolic tiles). MAP-Elites / multi-objective search would map an
  accuracy-vs-area-vs-power Pareto front rather than one winner. Scaling to large
  designs needs developmental/generative encodings (evolve the tiling rule, not
  the monolith) — the same decomposition instinct as "evolve the full-adder cell,
  compose," not "evolve the 12-bit adder."

See `paper/alife-lbw-draft.md` for the write-up (ALIFE 2026 late-breaking work).

## Running it

```
mrg run examples/ski_calculus/client_sdk_ga.py
```

`ski_ga_fpga.py` is the self-contained submission file (generated from
`ga_design.py` with the `Evaluator` wrapper removed so `GAEngine` is the unique
Wishbone-port top-level). Regenerate it / change K with the snippet in the repo
history.
