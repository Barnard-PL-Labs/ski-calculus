"""Simulation tests: run the SKI reducer in the Amaranth simulator and check
its rewritten graph against the pure-Python reference WHNF reducer.
"""

import importlib.util
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_ROOT))
import ski_term as st  # noqa: E402

amaranth_sim = pytest.importorskip("amaranth.sim")
Simulator = amaranth_sim.Simulator


def _design():
    spec = importlib.util.spec_from_file_location("ski_design", _ROOT / "design.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


design = _design()
SKISlave = design.SKISlave
HB = design.HEAP_BASE_WORD


def _wb_helpers(ctx, dut):
    async def write(adr, dat):
        ctx.set(dut.wb_cyc, 1)
        ctx.set(dut.wb_stb, 1)
        ctx.set(dut.wb_we, 1)
        ctx.set(dut.wb_adr, adr)
        ctx.set(dut.wb_dat_w, dat & 0xFFFFFFFF)
        for _ in range(8):
            await ctx.tick()
            if ctx.get(dut.wb_ack):
                break
        else:
            raise AssertionError(f"ack never fired writing adr={adr}")
        ctx.set(dut.wb_stb, 0)
        ctx.set(dut.wb_we, 0)
        ctx.set(dut.wb_cyc, 0)
        await ctx.tick()

    async def read(adr):
        ctx.set(dut.wb_cyc, 1)
        ctx.set(dut.wb_stb, 1)
        ctx.set(dut.wb_we, 0)
        ctx.set(dut.wb_adr, adr)
        for _ in range(8):
            await ctx.tick()
            if ctx.get(dut.wb_ack):
                break
        else:
            raise AssertionError(f"ack never fired reading adr={adr}")
        val = ctx.get(dut.wb_dat_r)
        ctx.set(dut.wb_stb, 0)
        ctx.set(dut.wb_cyc, 0)
        await ctx.tick()
        return val

    return write, read


def run_whnf(term, max_steps=0, timeout=20000):
    """Drive the DUT through one reduction and return (result_term, steps, status)."""
    nodes, root = st.serialize(term)
    dut = SKISlave()
    captured = {}

    async def drive(ctx):
        ctx.set(dut.wb_cyc, 0)
        ctx.set(dut.wb_stb, 0)
        await ctx.tick()
        write, read = _wb_helpers(ctx, dut)

        # Load the graph.
        for i, word in enumerate(nodes):
            await write(HB + i, word)
        await write(design.ROOT_WORD, root)
        await write(design.NODE_COUNT_WORD, len(nodes))
        await write(design.MAX_STEPS_WORD, max_steps)

        # Go.
        await write(design.CTRL_WORD, 1)
        for _ in range(timeout):
            if await read(design.CTRL_WORD) & 1:  # done
                break
        else:
            raise AssertionError("reduction never asserted done")

        captured["steps"] = await read(design.STEPS_WORD)
        captured["status"] = await read(design.STATUS_WORD)
        captured["alloc"] = await read(design.ALLOC_WORD)
        out_root = await read(design.ROOT_WORD)

        # Read back the whole heap up to the allocator high-water mark.
        heap = []
        for i in range(captured["alloc"]):
            heap.append(await read(HB + i))
        captured["term"] = st.parse(heap, out_root)

    sim = Simulator(dut)
    sim.add_clock(1 / 50e6)
    sim.add_testbench(drive)
    sim.run()
    return captured["term"], captured["steps"], captured["status"]


# --- Individual rules ----------------------------------------------------
def test_identity():
    term = st.App(st.I, st.K)
    out, steps, status = run_whnf(term)
    assert out == "K"
    assert status == 0
    assert steps == 1


def test_k():
    term = st.App(st.K, st.S, st.I)  # K S I -> S
    out, steps, _ = run_whnf(term)
    assert out == "S"
    assert steps == 1


def test_s_kk_identity():
    # S K K x -> x ; use x = I so the result is a clean leaf.
    term = st.App(st.S, st.K, st.K, st.I)
    out, steps, _ = run_whnf(term)
    assert out == "I"


# --- Cross-check against the reference on a batch of terms ----------------
@pytest.mark.parametrize("term", [
    st.App(st.I, st.I),
    st.App(st.I, st.S, st.K),                 # (I S) K -> S K
    st.App(st.K, st.I, st.S),
    st.App(st.K, st.App(st.K, st.I), st.S),
    st.App(st.S, st.K, st.K, st.S),
    st.App(st.S, st.K, st.I, st.K),
    st.App(st.S, st.S, st.K, st.I, st.I),
    st.App(st.S, st.App(st.K, st.S), st.K, st.I, st.K),
])
def test_matches_reference(term):
    ref, ref_steps, _ = st.reduce_whnf(term, max_steps=1000)
    out, steps, status = run_whnf(term, max_steps=1000)
    assert status == 0, f"unexpected status {status}"
    assert out == ref, f"hw {st.pretty(out)} != ref {st.pretty(ref)}"
    assert steps == ref_steps


# --- Guards --------------------------------------------------------------
def test_step_limit_flags():
    sii = st.App(st.S, st.I, st.I)
    omega = st.App(sii, sii)  # diverges
    out, steps, status = run_whnf(omega, max_steps=4)
    assert status & 0b10  # step-limit bit
    assert steps == 4


def test_bare_combinator_is_whnf():
    out, steps, status = run_whnf(st.S)
    assert out == "S"
    assert steps == 0
    assert status == 0
