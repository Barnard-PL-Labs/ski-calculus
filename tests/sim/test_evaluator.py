"""S2 sim tests: the hardware truth-table evaluator vs the S1 reference."""

import importlib.util
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_ROOT))
import ga_ref as gr  # noqa: E402
import ski_bool as sb  # noqa: E402

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


def hw_fitness(term, n_inputs, target_bits, max_steps=4000, timeout=200000):
    nodes, root = gr.serialize_template(term)
    dut = gd.Evaluator()
    res = {}

    async def drive(ctx):
        await ctx.tick()
        for i, w in enumerate(nodes):
            await _wr(ctx, dut, gd.EV_TMPL_BASE + i, w)
        await _wr(ctx, dut, gd.EV_TMPL_COUNT, len(nodes))
        await _wr(ctx, dut, gd.EV_CAND_ROOT, root)
        await _wr(ctx, dut, gd.EV_N_INPUTS, n_inputs)
        await _wr(ctx, dut, gd.EV_TARGET, gr.target_word(target_bits))
        await _wr(ctx, dut, gd.EV_MAX_STEPS, max_steps)
        await _wr(ctx, dut, gd.EV_CTRL, 1)
        for _ in range(timeout):
            if await _rd(ctx, dut, gd.EV_CTRL) & 1:
                break
        else:
            raise AssertionError("evaluator never finished")
        res["fitness"] = await _rd(ctx, dut, gd.EV_FITNESS)
        res["status"] = await _rd(ctx, dut, gd.EV_STATUS)

    sim = Simulator(dut)
    sim.add_clock(1 / 50e6)
    sim.add_testbench(drive)
    sim.run()
    return res["fitness"], res["status"]


# --- Known terms: hardware fitness must equal the reference fitness ------
CASES = [
    (sb.ID, 1, [0, 1]),           # identity boolean, perfect on its own table
    (sb.CONST_TRUE, 1, [1, 1]),
    (sb.CONST_FALSE, 1, [0, 0]),
    (sb.NOT, 1, [1, 0]),
    (sb.CONST_TRUE, 1, [1, 0]),    # partial: matches 1 of 2
    (sb.PROJ1, 2, [0, 0, 1, 1]),
    (sb.PROJ2, 2, [0, 1, 0, 1]),
    (sb.PROJ1, 2, [0, 1, 1, 0]),   # PROJ1 vs XOR target: partial
]


@pytest.mark.parametrize("term,n,target", CASES)
def test_hw_matches_reference(term, n, target):
    ref = sb.fitness(term, n, target, max_steps=4000)
    hw, status = hw_fitness(term, n, target)
    assert hw == ref, f"hw={hw} ref={ref} (status={status})"


def test_perfect_scores_full():
    # A perfect candidate scores all rows.
    hw, _ = hw_fitness(sb.NOT, 1, [1, 0])
    assert hw == 2
    hw, _ = hw_fitness(sb.PROJ1, 2, [0, 0, 1, 1])
    assert hw == 4
