"""S5 sim tests: the LFSR candidate generator produces well-formed pure-SKI terms,
and GACore/GAEngine run the autonomous generate->evaluate->count loop.
"""

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


def generate_one(seed, cand_size, template_depth=64):
    """Run the Generator once; return the template image it wrote + cand_root."""
    dut = gd.Generator(template_depth=template_depth)
    mem = [0] * template_depth
    res = {}

    async def drive(ctx):
        # Capture every template write the generator emits.
        ctx.set(dut.seed, seed)
        ctx.set(dut.cand_size, cand_size)
        ctx.set(dut.start, 1)
        await ctx.tick()
        ctx.set(dut.start, 0)
        for _ in range(5000):
            if ctx.get(dut.t_wen):
                mem[ctx.get(dut.t_waddr)] = ctx.get(dut.t_wdata)
            if ctx.get(dut.done):
                res["root"] = ctx.get(dut.cand_root)
                res["count"] = ctx.get(dut.tmpl_count)
                break
            await ctx.tick()
        else:
            raise AssertionError("generator never finished")

    sim = Simulator(dut)
    sim.add_clock(1 / 50e6)
    sim.add_testbench(drive)
    sim.run()
    return mem, res["root"], res["count"]


def _assert_wellformed(mem, root, count):
    # Preamble is intact.
    assert gr.decode(mem[gr.PTR_I]) == (gr.TAG_I, 0, 0)
    assert gr.decode(mem[gr.PTR_TRUE]) == (gr.TAG_K, 0, 0)
    assert gr.decode(mem[gr.PTR_T]) == (gr.TAG_T, 0, 0)
    assert gr.decode(mem[gr.PTR_F]) == (gr.TAG_F, 0, 0)
    # Every candidate node is a valid leaf or an app pointing to earlier nodes.
    for i in range(gr.PREAMBLE, count):
        tag, left, right = gr.decode(mem[i])
        assert tag in (gr.TAG_APP, gr.TAG_S, gr.TAG_K, gr.TAG_I)
        if tag == gr.TAG_APP:
            assert gr.PREAMBLE <= left < i, f"node {i} left={left} out of range"
            assert gr.PREAMBLE <= right < i, f"node {i} right={right} out of range"
    assert root == count - 1


def test_generator_wellformed_many_seeds():
    for seed in [1, 7, 12345, 0xDEADBEEF, 0x9E3779B1]:
        mem, root, count = generate_one(seed, cand_size=20)
        assert count == gr.PREAMBLE + 20
        _assert_wellformed(mem, root, count)


def test_generator_parses_as_term():
    # The generated candidate region must reconstruct as a finite SKI term.
    mem, root, count = generate_one(0xABCDEF, cand_size=16)
    term = gr.parse(mem, root)            # raises if cyclic/out-of-range
    # And it must be reducible to a definite boolean result on some input
    # (or cleanly time out) -- i.e. the reference can score it without error.
    f = sb.fitness(term, 1, [0, 1], max_steps=4000)
    assert 0 <= f <= 2


def test_generator_varies_with_seed():
    a, ra, _ = generate_one(1, 24)
    b, rb, _ = generate_one(2, 24)
    assert a[gr.PREAMBLE:] != b[gr.PREAMBLE:]  # different seeds -> different terms
