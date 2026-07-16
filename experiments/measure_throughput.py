"""Measure GA candidate throughput for one design at one clock.

Figure-1 data point: submits a design, waits for the build, runs REPS
free-running GA windows on whatever board the server flashed it to, and
reports throughput (total and per-core).

    python experiments/measure_throughput.py <design.py> [clk_mhz] [target_mhz]

Defaults: clk 50 MHz (the paper's baseline), target = clk.

Board-less submit (orchestrator #73): no board is pinned or held during the
build -- the build runs on Fargate against a build slot, and a board is
assigned only once there's a bitstream to flash. `app.fpga_id` is discovered
from the finished job.
"""
import functools, os, sys, time

import manhattan_reasoning_gym as mrg
import manhattan_reasoning_gym._client as _client

# Builds run on Fargate now, but a big design can still sit behind the build
# queue; keep the client deadline well past any single build.
_client.poll_job = functools.partial(_client.poll_job, timeout=10800)

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class Regs(mrg.cloud.RegisterMap):
    CTRL=0x00; SEED=0x04; N_INPUTS=0x08; TARGET=0x0C
    MAX_STEPS=0x10; CAND_SIZE=0x14; NUM_CORES=0x18
    TOTAL=0x1C; BEST=0x20; COUNT_BASE=0x40


N_INPUTS=2; TARGET_WORD=6; CAND_SIZE=16; MAX_STEPS=2000  # XOR [0,1,1,0] -> 6
RUN_S=5.0; REPS=6

design = sys.argv[1] if len(sys.argv) > 1 else os.path.join(_ROOT, "ski_ga_fpga_k16.py")
if not os.path.isabs(design):
    design = os.path.join(_ROOT, design)
clk_mhz = float(sys.argv[2]) if len(sys.argv) > 2 else 50.0
target_mhz = float(sys.argv[3]) if len(sys.argv) > 3 else clk_mhz
tag = os.path.basename(design).replace("ski_ga_fpga_", "").replace(".py", "")

app = mrg.cloud.App(
    f"thr_{tag}_{int(clk_mhz)}",
    design=design,
    sys_clk_freq=int(clk_mhz * 1e6),
    timing_target_mhz=target_mhz,
    registers=Regs,
)
print(f"[{time.strftime('%H:%M')}] {tag}: design clk {clk_mhz:.0f}MHz, "
      f"PnR target {target_mhz:.0f}MHz -- submitting (no board held)", flush=True)

t_build = time.monotonic()
thrs = []; solved = 0; cores = None
try:
    app._program()
    build_min = (time.monotonic() - t_build) / 60
    print(f"[{time.strftime('%H:%M')}] built + flashed to fpga{app.fpga_id} "
          f"in {build_min:.1f} min", flush=True)

    cores = app.read(Regs.NUM_CORES)
    print(f"  NUM_CORES = {cores}", flush=True)
    app.write(Regs.N_INPUTS, N_INPUTS); app.write(Regs.TARGET, TARGET_WORD)
    app.write(Regs.MAX_STEPS, MAX_STEPS); app.write(Regs.CAND_SIZE, CAND_SIZE)
    for rep in range(REPS):
        app.write(Regs.SEED, 0x1000 + rep * 0x9E37)
        app.write(Regs.CTRL, 1); t0 = time.monotonic(); time.sleep(RUN_S)
        total = app.read(Regs.TOTAL); el = time.monotonic() - t0
        best = app.read(Regs.BEST)
        app.write(Regs.CTRL, 0)
        thrs.append(total / el); solved += (best == 4)
        print(f"  rep{rep}: thr={total/el:,.0f}/s  best={best}/4", flush=True)
except Exception as e:
    print(f"FAIL {type(e).__name__}: {str(e)[:200]}", flush=True)
finally:
    try:
        app.release()
    except Exception:
        pass

clean = [t for t in thrs if t < 50_000_000]  # drop warm-up outliers
if clean:
    m = sum(clean) / len(clean)
    sd = (sum((x - m) ** 2 for x in clean) / len(clean)) ** 0.5
    per_core = m / cores if cores else float("nan")
    print(f"\nRESULT {tag} @ {clk_mhz:.0f}MHz (target {target_mhz:.0f}): "
          f"n={len(clean)} thr={m:,.0f}/s ± {sd:,.0f} "
          f"| {per_core:,.0f}/s/core over {cores} cores "
          f"| solved {solved}/{len(thrs)}", flush=True)
else:
    print(f"\nRESULT {tag} @ {clk_mhz:.0f}MHz: NO DATA", flush=True)
