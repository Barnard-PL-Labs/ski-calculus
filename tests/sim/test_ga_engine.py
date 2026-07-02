"""S5/S4 sim tests: the autonomous GA engine generates, evaluates, counts, and
tracks the best fitness across parallel cores -- driven entirely on-chip.
"""

import importlib.util
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_ROOT))
import ga_ref as gr  # noqa: E402

amaranth_sim = pytest.importorskip("amaranth.sim")
Simulator = amaranth_sim.Simulator


def _design():
    spec = importlib.util.spec_from_file_location("ga_design", _ROOT / "ga_design.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


gd = _design()


async def _wr(ctx, dut, a, v):
    ctx.set(dut.wb_cyc, 1); ctx.set(dut.wb_stb, 1); ctx.set(dut.wb_we, 1)
    ctx.set(dut.wb_adr, a); ctx.set(dut.wb_dat_w, v & 0xFFFFFFFF)
    for _ in range(8):
        await ctx.tick()
        if ctx.get(dut.wb_ack):
            break
    ctx.set(dut.wb_stb, 0); ctx.set(dut.wb_we, 0); ctx.set(dut.wb_cyc, 0)
    await ctx.tick()


async def _rd(ctx, dut, a):
    ctx.set(dut.wb_cyc, 1); ctx.set(dut.wb_stb, 1); ctx.set(dut.wb_we, 0)
    ctx.set(dut.wb_adr, a)
    for _ in range(8):
        await ctx.tick()
        if ctx.get(dut.wb_ack):
            break
    v = ctx.get(dut.wb_dat_r)
    ctx.set(dut.wb_stb, 0); ctx.set(dut.wb_cyc, 0)
    await ctx.tick()
    return v


def run_engine(target_bits, n_inputs, *, num_cores=2, cand_size=12,
               want_total=24, max_steps=1500, cycle_cap=4_000_000):
    dut = gd.GAEngine(num_cores=num_cores, template_depth=48, work_depth=256)
    res = {}

    async def drive(ctx):
        await ctx.tick()
        await _wr(ctx, dut, gd.GA_SEED, 0xC0FFEE)
        await _wr(ctx, dut, gd.GA_N_INPUTS, n_inputs)
        await _wr(ctx, dut, gd.GA_TARGET, gr.target_word(target_bits))
        await _wr(ctx, dut, gd.GA_MAX_STEPS, max_steps)
        await _wr(ctx, dut, gd.GA_CAND_SIZE, cand_size)
        assert (await _rd(ctx, dut, gd.GA_NUM_CORES)) == num_cores
        await _wr(ctx, dut, gd.GA_CTRL, 1)  # run

        cycles = 0
        total = 0
        while total < want_total and cycles < cycle_cap:
            for _ in range(2000):
                await ctx.tick()
            cycles += 2000
            total = await _rd(ctx, dut, gd.GA_TOTAL)

        await _wr(ctx, dut, gd.GA_CTRL, 0)  # stop
        for _ in range(50):
            await ctx.tick()
        res["total"] = await _rd(ctx, dut, gd.GA_TOTAL)
        res["best"] = await _rd(ctx, dut, gd.GA_BEST)
        res["per_core"] = [await _rd(ctx, dut, gd.GA_COUNT_BASE + i)
                           for i in range(num_cores)]
        res["cycles"] = cycles

    sim = Simulator(dut)
    sim.add_clock(1 / 50e6)
    sim.add_testbench(drive)
    sim.run()
    return res


def test_engine_counts_and_parallelism():
    # Constant-true target for 1 input: easy to score, exercises the full loop.
    r = run_engine([1, 1], 1, num_cores=2, want_total=24)
    assert r["total"] >= 24
    # Both cores contributed (true parallel throughput, not one core doing all).
    assert all(c > 0 for c in r["per_core"])
    assert sum(r["per_core"]) == r["total"]
    # Best fitness is a valid count and the engine found at least a partial match.
    assert 0 <= r["best"] <= 2
    assert r["best"] >= 1


def test_engine_best_is_valid_and_improves():
    # Best fitness must be a valid count, non-zero, and a larger search budget
    # never does worse (the loop genuinely explores).
    small = run_engine([1, 1], 1, num_cores=2, want_total=20, cand_size=10)
    big = run_engine([1, 1], 1, num_cores=2, want_total=120, cand_size=10)
    assert 1 <= small["best"] <= 2
    assert big["best"] >= small["best"]
    assert big["total"] >= 120


def test_throughput_cycles_per_candidate():
    # Report the in-sim cycles/candidate -- the basis for the S6 estimate.
    r = run_engine([0, 1], 1, num_cores=2, want_total=40, cand_size=12)
    cyc_per_cand = r["cycles"] * 1.0 / max(r["total"], 1)
    # Sanity bound; the real number is printed for the throughput model.
    assert cyc_per_cand < 200_000
    print(f"\n~{cyc_per_cand:.0f} sim-cycles per candidate "
          f"({r['total']} candidates, {r['cycles']} cycles, 2 cores)")
