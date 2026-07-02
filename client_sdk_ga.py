"""SKI genetic-algorithm throughput benchmark on the FPGA (stage S6).

Programs the K-core on-chip GA engine, lets it run free for a fixed wall-clock
window, and reports candidate-evaluation throughput (candidates/sec) plus the
best fitness the on-chip search reached. The host is NOT in the inner loop --
it only seeds the target and drains counters -- so this measures the fabric's
real evaluation rate.

Run with:
    mrg run examples/ski_calculus/client_sdk_ga.py
"""

import time

import manhattan_reasoning_gym as mrg


class Regs(mrg.RegisterMap):
    CTRL       = 0x00   # W bit0=run; R bit0=running bit1=any_busy
    SEED       = 0x04
    N_INPUTS   = 0x08
    TARGET     = 0x0C   # truth table: row r -> bit r
    MAX_STEPS  = 0x10
    CAND_SIZE  = 0x14
    NUM_CORES  = 0x18   # R
    TOTAL      = 0x1C   # R total candidates evaluated (sum over cores)
    BEST       = 0x20   # R global best fitness
    COUNT_BASE = 0x40   # R per-core count i at 0x40 + i*4


# Target boolean function to evolve (row order MSB-first). XOR of 2 inputs.
N_INPUTS = 2
TARGET_BITS = [0, 1, 1, 0]
CAND_SIZE = 16
MAX_STEPS = 2000
RUN_SECONDS = 5.0


def target_word(bits):
    w = 0
    for r, b in enumerate(bits):
        if b:
            w |= (1 << r)
    return w


app = mrg.App("ski_ga", design="examples/ski_calculus/ski_ga_fpga.py", registers=Regs)


@app.local_entrypoint()
def main():
    with app:
        num_cores = app.read(Regs.NUM_CORES)
        print(f"SKI GA engine: {num_cores} parallel cores")
        print(f"target n={N_INPUTS} table={TARGET_BITS} (XOR), "
              f"cand_size={CAND_SIZE}, max_steps={MAX_STEPS}\n")

        # Configure the search.
        app.write(Regs.SEED, 0x12345678)
        app.write(Regs.N_INPUTS, N_INPUTS)
        app.write(Regs.TARGET, target_word(TARGET_BITS))
        app.write(Regs.MAX_STEPS, MAX_STEPS)
        app.write(Regs.CAND_SIZE, CAND_SIZE)

        # Run free for a fixed wall-clock window; the cores evaluate on-chip.
        app.write(Regs.CTRL, 1)
        t0 = time.monotonic()
        time.sleep(RUN_SECONDS)
        total = app.read(Regs.TOTAL)
        elapsed = time.monotonic() - t0
        best = app.read(Regs.BEST)
        app.write(Regs.CTRL, 0)

        per_core = [app.read(Regs.COUNT_BASE + i * 4) for i in range(num_cores)]

        rate = total / elapsed if elapsed else 0
        print(f"=== THROUGHPUT (S6) ===")
        print(f"  candidates evaluated : {total:,}")
        print(f"  wall-clock window    : {elapsed:.2f} s")
        print(f"  throughput           : {rate:,.0f} candidates/sec")
        print(f"  per core             : {rate/num_cores:,.0f} candidates/sec/core")
        print(f"  best fitness         : {best}/{2**N_INPUTS}"
              f"{'  (SOLVED)' if best == 2**N_INPUTS else ''}")
        print(f"  per-core counts      : {per_core}")
