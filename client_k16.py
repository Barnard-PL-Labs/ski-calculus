"""K=16 SKI GA throughput run on real hardware.

Same benchmark as client_sdk_ga.py, but at K=16 cores and pinned to 120 MHz --
the configuration behind the headline ~2.48 M candidates/sec result (past a full
Apple M4). The ~13 min place-and-route for 16 cores fits comfortably inside the
SDK's default 40 min build-poll timeout, so no timeout override is needed.

    mrg run client_k16.py
"""

import time

import manhattan_reasoning_gym as mrg


class Regs(mrg.cloud.RegisterMap):
    CTRL = 0x00; SEED = 0x04; N_INPUTS = 0x08; TARGET = 0x0C
    MAX_STEPS = 0x10; CAND_SIZE = 0x14; NUM_CORES = 0x18
    TOTAL = 0x1C; BEST = 0x20; COUNT_BASE = 0x40


N_INPUTS = 2
TARGET_BITS = [0, 1, 1, 0]  # XOR
CAND_SIZE = 16
MAX_STEPS = 2000
RUN_SECONDS = 5.0


def target_word(bits):
    w = 0
    for r, b in enumerate(bits):
        if b:
            w |= (1 << r)
    return w


app = mrg.cloud.App("ski_ga_k16", design="ski_ga_fpga_k16.py",
                    registers=Regs, sys_clk_freq=120_000_000)


@app.local_entrypoint()
def main():
    with app:
        num_cores = app.read(Regs.NUM_CORES)
        print(f"SKI GA engine: {num_cores} parallel cores")
        print(f"target n={N_INPUTS} table={TARGET_BITS} (XOR), "
              f"cand_size={CAND_SIZE}, max_steps={MAX_STEPS}\n")

        app.write(Regs.SEED, 0x12345678)
        app.write(Regs.N_INPUTS, N_INPUTS)
        app.write(Regs.TARGET, target_word(TARGET_BITS))
        app.write(Regs.MAX_STEPS, MAX_STEPS)
        app.write(Regs.CAND_SIZE, CAND_SIZE)

        app.write(Regs.CTRL, 1)
        t0 = time.monotonic()
        time.sleep(RUN_SECONDS)
        total = app.read(Regs.TOTAL)
        elapsed = time.monotonic() - t0
        best = app.read(Regs.BEST)
        app.write(Regs.CTRL, 0)

        per_core = [app.read(Regs.COUNT_BASE + i * 4) for i in range(num_cores)]
        rate = total / elapsed if elapsed else 0
        print("=== THROUGHPUT (S6, K=16) ===")
        print(f"  candidates evaluated : {total:,}")
        print(f"  wall-clock window    : {elapsed:.2f} s")
        print(f"  throughput           : {rate:,.0f} candidates/sec")
        print(f"  per core             : {rate/num_cores:,.0f} candidates/sec/core")
        print(f"  best fitness         : {best}/{2**N_INPUTS}"
              f"{'  (SOLVED)' if best == 2**N_INPUTS else ''}")
        print(f"  per-core counts      : {per_core}")
