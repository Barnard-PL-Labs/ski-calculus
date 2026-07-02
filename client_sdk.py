"""SKI combinator-calculus evaluator on the FPGA, via the Cloud FPGA SDK.

Run with:
    mrg run client_sdk.py

Builds a few SKI terms, reduces each to weak head normal form (WHNF) on the
FPGA, and checks the hardware result against a pure-Python reference reducer.
Run `mrg login` first (or set MRG_API_KEY).

The heap is a flat array of 32-bit nodes (see design.py for the format). The
client serializes a term into nodes, writes them plus the root pointer, starts
the reducer, polls for done, then walks the rewritten graph back out.
"""

import manhattan_reasoning_gym as mrg

import ski_term as st
from ski_term import I, K, S, App

# How many reduction steps to allow before giving up (SKI terms can diverge).
MAX_STEPS = 100_000


class Regs(mrg.cloud.RegisterMap):
    # Mirror of design.py's word offsets, in bytes (word * 4). Pinned by tests.
    CTRL       = 0x0000  # W bit0=start; R bit0=done bit1=busy
    STATUS     = 0x0004  # R bit0=overflow bit1=step-limit
    ROOT       = 0x0008  # R/W root node pointer
    NODE_COUNT = 0x000C  # R/W nodes loaded (allocator start)
    MAX_STEPS  = 0x0010  # R/W step cap (0 = unlimited)
    STEPS      = 0x0014  # R steps performed
    ALLOC      = 0x0018  # R allocator high-water mark
    CAP        = 0x001C  # R heap capacity (nodes)
    HEAP       = 0x0040  # node i lives at HEAP + i*4


app = mrg.cloud.App(
    "ski_calculus",
    design="design.py",
    registers=Regs,
)


def reduce_on_fpga(term):
    """Reduce one term to WHNF on the FPGA; print and verify against reference."""
    nodes, root = st.serialize(term)

    cap = app.read(Regs.CAP)
    if len(nodes) > cap:
        raise RuntimeError(f"term needs {len(nodes)} nodes, heap holds {cap}")

    # Load the graph, then the run parameters.
    app.write(Regs.HEAP, nodes)          # burst-write all node words
    app.write(Regs.ROOT, root)
    app.write(Regs.NODE_COUNT, len(nodes))
    app.write(Regs.MAX_STEPS, MAX_STEPS)

    app.write(Regs.CTRL, 1)              # start
    while not (app.read(Regs.CTRL) & 1):  # poll done
        pass

    status = app.read(Regs.STATUS)
    steps = app.read(Regs.STEPS)
    alloc = app.read(Regs.ALLOC)
    out_root = app.read(Regs.ROOT)

    if status & 0b01:
        raise RuntimeError(f"heap overflow after {steps} steps")

    # Walk the rewritten graph back out of the heap.
    heap = app.read(Regs.HEAP, count=alloc)
    result = st.parse(heap, out_root)

    ref, ref_steps, _ = st.reduce_whnf(term, max_steps=MAX_STEPS)
    limited = " (step limit hit)" if status & 0b10 else ""
    ok = result == ref
    print(f"{st.pretty(term):<28} -> {st.pretty(result):<16} "
          f"[{steps} steps{limited}, {'OK' if ok else 'MISMATCH'}]")
    if not ok and not (status & 0b10):
        raise AssertionError(
            f"hardware {st.pretty(result)} != reference {st.pretty(ref)}")


@app.local_entrypoint()
def main():
    with app:
        print(f"SKI WHNF reducer  (heap capacity: {app.read(Regs.CAP)} nodes)\n")

        reduce_on_fpga(App(I, K))                    # I K          -> K
        reduce_on_fpga(App(K, S, I))                 # K S I        -> S
        reduce_on_fpga(App(S, K, K, I))              # S K K I      -> I
        reduce_on_fpga(App(S, K, S, K))              # S K S K      -> K
        reduce_on_fpga(App(S, App(K, S), K, I, K))   # nested
        # (S K K) is the identity combinator; apply it to a compound argument.
        reduce_on_fpga(App(S, K, K, App(K, I)))      # -> K I
